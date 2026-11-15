"""BRAIN-07J: bind canonical accepted predecessor evidence to journal outputs.

This is a pure pre-dispatch verification adapter, NOT a scheduler, worker
launcher, lease, approval or a completion authority. A missing digest from an
older accepted result MUST fail closed: no result is retroactively trusted.
"""
from __future__ import annotations

import copy
import hashlib
import hmac
import json
import re

from modules import goal_plan_gate, goal_state

_SHA256 = re.compile(r'[0-9a-f]{64}\Z')


def output_sha256(output: dict) -> str:
    """Hash precisely the clean JSON result returned to the execution journal.

    The transport-only _worker_result envelope never belongs to that output.
    JSON canonicalization matches existing Core input_digest conventions.
    """
    if not isinstance(output, dict):
        raise ValueError('Predecessor output must be a JSON object.')
    clean = copy.deepcopy(output)
    clean.pop('_worker_result', None)
    encoded = json.dumps(
        clean, ensure_ascii=False, sort_keys=True, separators=(',', ':'),
        allow_nan=False,
    ).encode('utf-8')
    return hashlib.sha256(encoded).hexdigest()


def bind_predecessor_outputs(
    state: dict,
    selection: goal_plan_gate.NodeCandidate,
    journal_outputs: dict,
) -> dict[str, dict]:
    """Return defensively copied direct dependencies only after exact proof.

    The Core gate must first consider the selected node ready based on
    canonical accepted worker evidence. For *each* predecessor, require the
    unique accepted success from the current plan to commit a digest of the
    exact ExecutionRecord output and independently re-verify its domain proof.
    An old/unsigned success, changed file, wrong owner, stale plan, missing
    output or forged journal value cannot be used as a dependent input.
    """
    node = goal_plan_gate.revalidate(state, selection)
    if not node['depends_on']:
        raise goal_plan_gate.PlanFenceError(
            'Predecessor binding is only for canonical dependent nodes.'
        )
    if not isinstance(journal_outputs, dict):
        raise goal_plan_gate.PlanFenceError('ExecutionRecord outputs invalid.')
    ready = goal_plan_gate.ready_read_only_candidates(
        state, owner=selection.owner, job_id=selection.job_id,
    )
    if selection not in ready:
        raise goal_plan_gate.PlanFenceError(
            'Dependent node has no complete canonical predecessor evidence.'
        )
    current = goal_state.validate(state)
    result: dict[str, dict] = {}
    from modules import goal_tools

    for step_id in node['depends_on']:
        commits = [
            row for row in current['evidence']
            if isinstance(row, dict)
            and row.get('kind') == 'worker_result'
            and row.get('owner') == selection.owner
            and row.get('job_id') == selection.job_id
            and row.get('plan_version') == selection.plan_version
            and row.get('step_id') == step_id
            and row.get('status') == 'succeeded'
        ]
        if len(commits) != 1:
            raise goal_plan_gate.PlanFenceError(
                'Predecessor must have exactly one accepted success.'
            )
        accepted = commits[0].get('evidence')
        if (not isinstance(accepted, list) or len(accepted) != 1
                or not isinstance(accepted[0], dict)):
            raise goal_plan_gate.PlanFenceError(
                'Accepted predecessor output commitment is missing.'
            )
        proof = accepted[0]
        digest = proof.get('output_sha256')
        output = journal_outputs.get(step_id)
        if (not isinstance(digest, str) or not _SHA256.fullmatch(digest)
                or not isinstance(output, dict)
                or output.get('state') != 'done'
                or '_worker_result' in output
                or proof.get('state') != 'done'
                or proof.get('verification') != output.get('verification')):
            raise goal_plan_gate.PlanFenceError(
                'Predecessor journal/evidence identity or commitment mismatched.'
            )
        try:
            actual = output_sha256(output)
        except (TypeError, ValueError, OverflowError):
            raise goal_plan_gate.PlanFenceError(
                'Predecessor journal output is not canonical JSON.'
            ) from None
        if not hmac.compare_digest(digest, actual):
            raise goal_plan_gate.PlanFenceError(
                'Predecessor output differs from accepted canonical evidence.'
            )
        try:
            verified = goal_tools.verify(output, selection.owner)
        except (ValueError, PermissionError, OSError, KeyError, TypeError):
            raise goal_plan_gate.PlanFenceError(
                'Predecessor domain result is no longer verifiable.'
            ) from None
        if verified is not True:
            raise goal_plan_gate.PlanFenceError(
                'Predecessor domain verifier did not confirm output.'
            )
        result[step_id] = copy.deepcopy(output)
    return result


def preflight_durable_step(
    identity: dict, step: dict, journal_outputs: dict, *,
    owner: str | None = None, job_id: str | None = None,
    canonical_required: bool = False,
) -> dict[str, dict] | None:
    """Validate canonical dependent inputs at the existing specialist boundary.

    Returns None for an unplanned/legacy call, preserving its existing
    dependency semantics; a *planned* dependent step returns only trusted
    copies from bind_predecessor_outputs. This does not enable its worker:
    runtime_worker_result.prepare and worker_result_commit still deny
    dependent execution until the separate Core dispatch cutover.
    """
    from modules import (
        capability_manifest, goal_executor, goal_state_store,
        runtime_worker_result,
    )
    if not isinstance(identity, dict):
        raise goal_plan_gate.PlanFenceError('Specialist identity invalid.')
    if ((owner is not None and identity.get('owner') != owner)
            or (job_id is not None and identity.get('job_id') != job_id)):
        raise goal_plan_gate.PlanFenceError(
            'Specialist identity differs from durable execution owner/job.'
        )
    if not runtime_worker_result.durable_identity(identity):
        # Partial planned identity is not a legacy identity. Even if the
        # canonical sidecar disappeared and the transient job version marker
        # was stripped, a plan fence cannot authorize legacy dispatch.
        if 'plan_version' in identity or 'node_digest' in identity:
            raise goal_plan_gate.PlanFenceError(
                'Canonical plan fence requires durable worker identity.'
            )
        # A planned canonical job cannot escape dependency proof simply by
        # supplying an old, unversioned specialist identity. The former
        # unplanned/legacy specialist path is preserved.
        if isinstance(owner, str) and isinstance(job_id, str):
            path = goal_executor._root(owner) / (job_id + '.goalstate.json')
            try:
                current = goal_state_store.load(path)
            except FileNotFoundError:
                if canonical_required:
                    raise goal_plan_gate.PlanFenceError(
                        'Expected canonical GoalState is missing.'
                    ) from None
                return None
            if current.get('goal_plan') is not None:
                raise goal_plan_gate.PlanFenceError(
                    'Canonical dependent requires durable worker identity.'
                )
        return None
    if not isinstance(step, dict) or not isinstance(journal_outputs, dict):
        raise goal_plan_gate.PlanFenceError('Durable step or outputs invalid.')
    try:
        state = runtime_worker_result.canonical_snapshot(identity)
    except FileNotFoundError:
        # Standalone historical specialist/approval calls can use versioned
        # identities without a canonical GoalState. Do not turn those into
        # planned DAG work. Conversely, an executor-proven canonical job or
        # explicitly plan-fenced identity must never downgrade on file loss.
        if (canonical_required or 'plan_version' in identity
                or 'node_digest' in identity):
            raise goal_plan_gate.PlanFenceError(
                'Expected canonical GoalState is missing.'
            ) from None
        return None
    if state.get('goal_plan') is None:
        return None

    selected = goal_plan_gate.candidate(
        state, owner=identity.get('owner'), job_id=identity.get('job_id'),
        node_id=identity.get('task_id'),
    )
    node = goal_plan_gate.revalidate(state, selected)
    depends = step.get('depends')
    kind = step.get('tool')
    if (step.get('id') != identity.get('task_id')
            or not isinstance(depends, list)
            or depends != node['depends_on']
            or not isinstance(kind, str)
            or node['input'] != step.get('input')):
        raise goal_plan_gate.PlanFenceError(
            'Durable specialist step does not match the canonical plan node.'
        )
    try:
        try:
            manifest = capability_manifest.from_task_tool(kind)
        except ValueError:
            manifest = capability_manifest.from_goal_tool(kind)
    except ValueError:
        raise goal_plan_gate.PlanFenceError(
            'Unknown specialist capability in canonical dependent plan.'
        ) from None
    if manifest['id'] != node['capability_id']:
        raise goal_plan_gate.PlanFenceError(
            'Specialist tool and canonical capability do not match.'
        )
    if not depends:
        return {}

    # Read from the existing durable ExecutionRecord, not merely a mutable
    # in-memory job dict supplied to the worker adapter. A canonical dependent
    # must never be launched from an unpersisted or legacy-only output claim.
    from modules import execution_record
    root = goal_executor._root(selected.owner)
    path = execution_record.path_for(root, selected.job_id)
    if path.is_symlink() or not path.is_file():
        raise goal_plan_gate.PlanFenceError(
            'Canonical dependent requires a persisted ExecutionRecord.'
        )
    try:
        persisted = execution_record.load(
            root, selected.owner, selected.job_id,
        )
    except (OSError, ValueError, TypeError, PermissionError):
        raise goal_plan_gate.PlanFenceError(
            'Cannot validate persisted ExecutionRecord.'
        ) from None
    disk_outputs = persisted.get('outputs')
    if not isinstance(disk_outputs, dict) or any(
        key not in journal_outputs or key not in disk_outputs
        or journal_outputs[key] != disk_outputs[key]
        for key in depends
    ):
        raise goal_plan_gate.PlanFenceError(
            'In-memory dependent input differs from persisted ExecutionRecord.'
        )
    return bind_predecessor_outputs(state, selected, disk_outputs)


def _require_persisted_dependencies(
    identity: dict, node: dict, capability: str,
) -> dict[str, dict]:
    """Bind already accepted, projected predecessor bytes from the journal."""
    from modules import execution_record, goal_executor
    if (capability not in ('task.research', 'task.account', 'task.verify',
                           'task.writer', 'task.publish')
            or not isinstance(identity, dict) or not isinstance(node, dict)
            or node.get('capability_id') != capability
            or not isinstance(node.get('depends_on'), list)
            or not node['depends_on']):
        raise goal_plan_gate.PlanFenceError('Dependent read-only boundary invalid.')
    owner = identity.get('owner')
    job_id = identity.get('job_id')
    if not isinstance(owner, str) or not isinstance(job_id, str):
        raise goal_plan_gate.PlanFenceError('Dependent owner/job identity missing.')
    root = goal_executor._root(owner)
    path = execution_record.path_for(root, job_id)
    if path.is_symlink() or not path.is_file():
        raise goal_plan_gate.PlanFenceError(
            'Dependent read-only requires a persisted ExecutionRecord.'
        )
    try:
        persisted = execution_record.load(root, owner, job_id)
    except (OSError, ValueError, TypeError, PermissionError):
        raise goal_plan_gate.PlanFenceError(
            'Dependent read-only ExecutionRecord is invalid.'
        ) from None
    return preflight_durable_step(
        identity,
        {
            'id': identity.get('task_id'),
            'tool': capability.removeprefix('task.'),
            'depends': copy.deepcopy(node['depends_on']),
            'input': copy.deepcopy(node['input']),
        },
        persisted.get('outputs'),
        owner=owner, job_id=job_id, canonical_required=True,
    )


def require_persisted_research_dependencies(identity: dict, node: dict) -> dict[str, dict]:
    """Reverify exact projected research parents before dispatch and Core CAS."""
    return _require_persisted_dependencies(identity, node, 'task.research')


def require_persisted_account_dependencies(identity: dict, node: dict) -> dict[str, dict]:
    """Reverify exact projected account parents before Gmail indexed read."""
    return _require_persisted_dependencies(identity, node, 'task.account')


def require_persisted_verify_dependencies(identity: dict, node: dict) -> dict[str, dict]:
    """Validate all parent SHA-256 commitments and domain receipts."""
    return _require_persisted_dependencies(identity, node, 'task.verify')



def require_persisted_effect_dependencies(identity: dict, node: dict) -> dict[str, dict]:
    """A writer/publish worker reads only accepted and projected source bytes.

    Each source is re-verified against the exact Core result digest and native
    artifact/receipt before any new report or outbound send is permitted.
    """
    capability = node.get('capability_id') if isinstance(node, dict) else None
    if capability not in ('task.writer', 'task.publish'):
        raise goal_plan_gate.PlanFenceError('Unsupported dependent effect.')
    return _require_persisted_dependencies(identity, node, capability)
