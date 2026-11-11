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


def _read_only_manifest(capability_id: str) -> dict | None:
    """Resolve the existing developer-integrated capability catalog only."""
    from modules import capability_manifest
    if not isinstance(capability_id, str):
        return None
    try:
        if capability_id.startswith('task.'):
            spec = capability_manifest.from_task_tool(capability_id.removeprefix('task.'))
        elif capability_id.startswith('goal.'):
            spec = capability_manifest.from_goal_tool(capability_id.removeprefix('goal.'))
        else:
            return None
    except ValueError:
        return None
    if (spec['id'] != capability_id or spec['effect_policy'] != 'read_only'
            or spec['decision_authority'] != 'execute'):
        return None
    return spec


def ready_read_only_candidates(
    state: dict, *, owner: str, job_id: str,
) -> tuple[NodeCandidate, ...]:
    """Find snapshot-ready plan nodes from *accepted canonical worker evidence*.

    This is read-only eligibility, NOT permission, admission, lease acquisition,
    worker dispatch or global completion. A failed node is not automatically
    retried; revision/cancel and any unexpected evidence fail closed.
    """
    current, plan = _current_plan(state)
    if (owner, job_id) != (current['owner'], current['job_id']):
        raise PlanFenceError('Yanlış plan owner/job kimliği.')

    # A later user correction or priority edit is not automatically reconciled
    # into an earlier plan. Require the canonical planner to publish a newer
    # plan after that intent change before any new read-only dispatch candidate.
    plan_commits = [index for index, entry in enumerate(current['audit'])
                    if entry['op'] == 'set_goal_plan']
    if not plan_commits or any(
        entry['op'] == 'mutate_goal_intent'
        for entry in current['audit'][plan_commits[-1] + 1:]
    ):
        raise PlanFenceError('Kullanıcı goal intent değişikliği için plan revalidation gerekli.')

    # Audit appends are ordered and each append_evidence creates exactly one
    # evidence entry. A merely worker-shaped dict is not trusted without the
    # existing WORKER_RESULT_ACCEPTED audit reason.
    appends = [row for row in current['audit'] if row['op'] == 'append_evidence']
    if len(appends) != len(current['evidence']):
        raise PlanFenceError('GoalState evidence/audit sırası doğrulanamadı.')

    nodes = {node['id']: node for node in plan['nodes']}
    digests = fingerprints(plan)
    seen: dict[str, tuple[int, str]] = {}
    completed: set[str] = set()
    for audit, evidence in zip(appends, current['evidence']):
        row = evidence if isinstance(evidence, dict) else {}
        claimed = row.get('kind') == 'worker_result'
        accepted = audit['reason_code'] == 'WORKER_RESULT_ACCEPTED'
        if claimed != accepted:
            raise PlanFenceError('WorkerResult evidence/audit authority tutarsız.')
        if not claimed:
            continue
        # The canonical plan was revised; previous success is not transferable
        # by a name match and must not be counted as current-plan completion.
        if row.get('plan_version') != plan['plan_version']:
            continue

        step = row.get('step_id')
        node = nodes.get(step) if isinstance(step, str) else None
        if node is None:
            raise PlanFenceError('Current-plan WorkerResult step belirsiz.')
        spec = _read_only_manifest(node['capability_id'])
        attempt = row.get('attempt')
        digest = _hash(node['input'])  # same canonical-input JSON hash used by runtime
        if (spec is None
                or row.get('owner') != owner or row.get('job_id') != job_id
                or row.get('capability_id') != node['capability_id']
                or row.get('capability_version') != str(spec['version'])
                or row.get('node_digest') != digests[step]
                or row.get('input_digest') != digest
                or type(attempt) is not int or attempt < 1
                or row.get('command_id') !=
                   f"{step}:{attempt}:p{plan['plan_version']}"
                or row.get('status') not in ('succeeded', 'failed')
                or not isinstance(row.get('evidence'), list)):
            raise PlanFenceError('Current-plan WorkerResult canonical fence geçersiz.')
        prior = seen.get(step)
        if prior is not None and (prior[1] == 'succeeded' or attempt <= prior[0]):
            raise PlanFenceError('Current-plan WorkerResult attempt sırası belirsiz.')
        # An explicitly retried failure may later succeed, but a previously
        # succeeded node cannot be accepted as a new generation of work.
        seen[step] = (attempt, row['status'])
        if row['status'] == 'succeeded':
            completed.add(step)

    # A dependency never becomes ready just because a model or output reports
    # done: every prerequisite needs its own accepted WorkerResult audit.
    return tuple(
        candidate(current, owner=owner, job_id=job_id, node_id=node['id'])
        for node in plan['nodes']
        if (node['id'] not in seen
            and all(dep in completed for dep in node['depends_on'])
            and _read_only_manifest(node['capability_id']) is not None)
    )


def validate_root_attempt(
    state: dict, selection: NodeCandidate, *, attempt: int,
) -> dict:
    """Fence one read-only root before worker launch or canonical result CAS.

    The existing executor chooses retry attempts; this gate does not grant a
    retry, lease, permission, scheduler slot, or completion. Success is terminal
    for this plan root. A previous failed attempt can only be followed by a
    strictly newer attempt, never silently replayed with changed evidence.
    """
    if type(attempt) is not int or not 1 <= attempt <= 1_000_000:
        raise PlanFenceError('Root attempt kimliği geçersiz.')
    node = revalidate(state, selection)
    if node['depends_on']:
        raise PlanFenceError('Bağımlı node üretim worker dispatch kapsamı dışında.')

    # In addition to node + snapshot identity, this rejects unplanned intent
    # edits, invalid acceptance audits, tampered evidence, effectful tools,
    # and work already accepted as complete. No second status store exists.
    ready = ready_read_only_candidates(
        state, owner=selection.owner, job_id=selection.job_id,
    )
    if selection in ready:
        return node

    current = goal_state.validate(state)
    old = [
        row for row in current['evidence']
        if isinstance(row, dict) and row.get('kind') == 'worker_result'
        and row.get('owner') == selection.owner
        and row.get('job_id') == selection.job_id
        and row.get('step_id') == selection.node_id
        and row.get('plan_version') == selection.plan_version
    ]
    if (old and old[-1].get('status') == 'failed'
            and attempt > old[-1].get('attempt', -1)):
        # All current-plan worker rows, including this failed attempt, have
        # already been checked by ready_read_only_candidates above.
        return node
    raise PlanFenceError(
        'Canonical root tamamlanmış, durmuş veya geçerli attempt bekliyor.'
    )


def validate_dependent_research_attempt(
    state: dict, selection: NodeCandidate, *, attempt: int,
) -> dict:
    """Admit only a first-attempt, canonical, evidence-ready research child.

    Readiness is not output binding or worker authority. A separate persistent
    predecessor readback must precede dispatch AND final WorkerResult CAS.
    No dependent retry, account/file/desktop effect, or lease is granted here.
    """
    if type(attempt) is not int or attempt != 1:
        raise PlanFenceError('Dependent research requires a fresh first attempt.')
    node = revalidate(state, selection)
    if (not node['depends_on']
            or node['capability_id'] != 'task.research'
            or selection not in ready_read_only_candidates(
                state, owner=selection.owner, job_id=selection.job_id,
            )):
        raise PlanFenceError(
            'Dependent research has no fresh canonical predecessor readiness.'
        )
    return node


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
