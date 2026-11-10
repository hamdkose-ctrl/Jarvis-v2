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
