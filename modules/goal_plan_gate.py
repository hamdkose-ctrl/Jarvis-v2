"""BRAIN-06B: pure canonical DAG node fingerprints and revision/dispatch fences.

Read-only preparation checks, not a scheduler, worker-result verifier, permission
grant, executor, or source of accepted completion evidence. No extra GoalState
store is created here.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json

from modules import goal_state


class PlanFenceError(ValueError):
    """A node or plan candidate is stale, invalid, or cannot be dispatched."""


@dataclass(frozen=True)
class NodeCandidate:
    owner: str
    job_id: str
    expected_goal_version: int
    plan_version: int
    node_id: str
    capability_id: str
    node_digest: str


def _hash(value: dict) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True,
                         separators=(',', ':'), allow_nan=False).encode('utf-8')
    return hashlib.sha256(encoded).hexdigest()


def fingerprints(plan: dict) -> dict[str, str]:
    """Hash every node and transitive prerequisites using validated DAG order.

    Any change in an ancestor's input, capability, acceptance, output or edges
    invalidates the fingerprints of all dependent nodes.
    """
    graph = goal_state.validate_goal_plan(plan)
    fingerprints_by_id: dict[str, str] = {}
    for node in graph['nodes']:
        dependencies = [
            {'id': dep, 'fingerprint': fingerprints_by_id[dep]}
            for dep in node['depends_on']
        ]
        fingerprints_by_id[node['id']] = _hash({
            'node': node,
            'dependencies': dependencies,
        })
    return fingerprints_by_id


def _current_plan(state: dict) -> tuple[dict, dict]:
    current = goal_state.validate(state)
    if goal_state.authority(current) != 'canonical':
        raise PlanFenceError('Canonical plan authority gerekli.')
    if current['state'] not in ('pending', 'running'):
        raise PlanFenceError('Plan node yalnız aktif/pending hedefte hazırlanabilir.')
    plan = current.get('goal_plan')
    if plan is None:
        raise PlanFenceError('Canonical GoalState planı yok.')
    return current, plan


def candidate(state: dict, *, owner: str, job_id: str, node_id: str) -> NodeCandidate:
    """Snapshot a node identity for later Core pre-dispatch revalidation.

    The result is only a candidate. Neither node readiness nor permissions,
    approval, resource leases, or accepted worker output are implied.
    """
    current, plan = _current_plan(state)
    if (owner, job_id) != (current['owner'], current['job_id']):
        raise PlanFenceError('Başka kullanıcının/hedefin planına erişim reddedildi.')
    if not isinstance(node_id, str):
        raise PlanFenceError('Node kimliği geçersiz.')
    match = next((n for n in plan['nodes'] if n['id'] == node_id), None)
    if match is None:
        raise PlanFenceError('Seçilen node mevcut planda bulunmuyor.')
    return NodeCandidate(
        owner=current['owner'], job_id=current['job_id'],
        expected_goal_version=current['version'],
        plan_version=plan['plan_version'],
        node_id=node_id, capability_id=match['capability_id'],
        node_digest=fingerprints(plan)[node_id],
    )


def revalidate(state: dict, selection: NodeCandidate) -> dict:
    """Reject stale candidates *before* any permission, lease or dispatch step."""
    if not isinstance(selection, NodeCandidate):
        raise PlanFenceError('Plan node candidate türü geçersiz.')
    current, plan = _current_plan(state)
    if (selection.owner, selection.job_id) != (current['owner'], current['job_id']):
        raise PlanFenceError('Plan node başka owner/job kimliğine ait.')
    if selection.expected_goal_version != current['version']:
        raise PlanFenceError('Plan node GoalState sürümü stale.')
    if selection.plan_version != plan['plan_version']:
        raise PlanFenceError('Plan node sürümü stale.')
    node = next((n for n in plan['nodes'] if n['id'] == selection.node_id), None)
    if node is None or node['capability_id'] != selection.capability_id:
        raise PlanFenceError('Plan node/capability değişti.')
    if fingerprints(plan)[selection.node_id] != selection.node_digest:
        raise PlanFenceError('Plan node veya önceki bağımlılık değişti.')
    return node


def initial_roots(state: dict, *, owner: str, job_id: str) -> tuple[NodeCandidate, ...]:
    """Return only dependency-free candidates; not a scheduling decision."""
    current, plan = _current_plan(state)
    if (owner, job_id) != (current['owner'], current['job_id']):
        raise PlanFenceError('Yanlış plan owner/job kimliği.')
    return tuple(
        candidate(current, owner=owner, job_id=job_id, node_id=n['id'])
        for n in plan['nodes'] if not n['depends_on']
    )


def revision_reuse_candidates(state: dict, revised_plan: dict) -> tuple[str, ...]:
    """Return structurally unchanged node IDs, *not* verified finished steps.

    Completion evidence and approval must be reverified by Core separately.
    No worker can be skipped solely on this result.
    """
    current, previous = _current_plan(state)
    proposed = goal_state.validate_goal_plan(revised_plan)
    if proposed['plan_version'] != previous['plan_version'] + 1:
        raise PlanFenceError('Plan revizyonu sürümü sıralı değil.')
    old = fingerprints(previous)
    new = fingerprints(proposed)
    return tuple(node['id'] for node in proposed['nodes']
                 if old.get(node['id']) == new[node['id']])
