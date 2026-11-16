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


def worker_compatible_audit(row: dict) -> bool:
    """Only accepted sibling work or scheduling-only Core changes may overlap.

    A pause REQUEST lets the already admitted step reach its checkpoint;
    actual pause/resume, revised intent and plan changes still revoke it.
    """
    return (row.get('op'), row.get('reason_code')) in {
        ('append_evidence', 'WORKER_RESULT_ACCEPTED'),
        ('mutate_goal_intent', 'USER_GOAL_PRIORITY'),
        ('set_blocker', 'USER_GOAL_PAUSE_REQUESTED'),
        ('clear_blocker', 'USER_GOAL_PAUSE_WITHDRAWN'),
    }


def projection_compatible_audit(row: dict) -> bool:
    return worker_compatible_audit(row) or (row.get('op'), row.get('reason_code')) in {
        ('set_state', 'USER_GOAL_PAUSED'),
        ('set_blocker', 'USER_GOAL_PAUSED'),
        ('set_state', 'USER_GOAL_RESUMED'),
    }


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


_SCHEDULED_EFFECTS = frozenset({'task.writer', 'task.coder', 'task.publish', 'task.media'})


def _scheduled_manifest(capability_id: str) -> dict | None:
    """Developer-installed read-only or explicitly admitted effect adapter.

    This does not grant an effect: live approval, resources, WorkerResult and
    persistent intent are independently checked by the single Scheduler.
    """
    from modules import capability_manifest
    safe = _read_only_manifest(capability_id)
    if safe is not None:
        return safe
    if capability_id not in _SCHEDULED_EFFECTS:
        return None
    try:
        row = capability_manifest.from_task_tool(capability_id.removeprefix('task.'))
    except ValueError:
        return None
    return row if row['id'] == capability_id else None


def _effect_node_allowed(plan: dict, node: dict) -> bool:
    """No arbitrary effectful DAG from a forged or revised GoalPlan."""
    kind = node['capability_id']
    if kind not in _SCHEDULED_EFFECTS:
        return True
    parents = {p['id']:p for p in plan['nodes']}
    deps = node['depends_on']
    if kind == 'task.media':
        return not deps
    if kind == 'task.coder':
        return not deps
    if kind == 'task.writer':
        return all(parents[d]['capability_id']
                   in ('task.research','task.account','task.verify') for d in deps)
    if kind == 'task.publish':
        return (not node['input'].get('source_task')
                and (not deps or (len(deps)==1
                                  and parents[deps[0]]['capability_id']=='task.writer'
                                  and node['input'].get('text_from_task')==deps[0])))
    return False


def validate_dependent_effect_attempt(state: dict, selection: NodeCandidate,
                                      *, attempt: int) -> dict:
    """A writer/publish child requires exact accepted, projected parent bytes."""
    if type(attempt) is not int or attempt != 1:
        raise PlanFenceError('Effectful dependent may not automatically retry.')
    node = revalidate(state, selection)
    if (node['capability_id'] not in ('task.writer','task.publish')
            or not node['depends_on']
            or not _effect_node_allowed(state['goal_plan'], node)
            or selection not in ready_read_only_candidates(
                state, owner=selection.owner, job_id=selection.job_id)):
        raise PlanFenceError('Effectful child requires accepted trusted predecessors.')
    return node


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
        entry['op'] == 'mutate_goal_intent' and entry['reason_code'] != 'USER_GOAL_PRIORITY'
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
    if any(_scheduled_manifest(node['capability_id']) is None
           or not _effect_node_allowed(plan, node) for node in plan['nodes']):
        raise PlanFenceError('Unknown or invalid scheduled capability/dependency.')
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
        spec = _scheduled_manifest(node['capability_id'])
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
            and _scheduled_manifest(node['capability_id']) is not None
            and _effect_node_allowed(plan, node))
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
        # A previously unattempted node has exactly one authorized initial
        # command generation. Higher attempts require a durable failed result;
        # an arbitrary caller must not manufacture a retry before attempt 1.
        if attempt != 1:
            raise PlanFenceError('Fresh canonical root requires first attempt.')
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
            'Bağımlı araştırma için güncel canonical predecessor kanıtı yok.'
        )
    return node


def validate_dependent_verify_attempt(
    state: dict, selection: NodeCandidate, *, attempt: int,
) -> dict:
    """First-attempt verify of already Core-accepted, read-only predecessors."""
    if type(attempt) is not int or attempt != 1:
        raise PlanFenceError('Dependent verify cannot automatically retry.')
    node = revalidate(state, selection)
    parents = {row['id']: row for row in state['goal_plan']['nodes']}
    if (node['capability_id'] != 'task.verify'
            or not 1 <= len(node['depends_on']) <= 6
            or any(parents.get(dep, {}).get('capability_id')
                   not in ('task.research', 'task.account')
                   for dep in node['depends_on'])
            or selection not in ready_read_only_candidates(
                state, owner=selection.owner, job_id=selection.job_id,
            )):
        raise PlanFenceError('Verify requires accepted read-only predecessor proofs.')
    return node


def supported_gmail_indexed_dependency(plan: dict, node: dict) -> bool:
    """Structural allowlist, not completion proof or dispatch authority.

    Same exact shape guards both fresh dependent-account admission and the
    already-accepted child rows a concurrent independent root may observe.
    """
    if (not isinstance(plan, dict) or not isinstance(node, dict)
            or node.get('capability_id') != 'task.account'
            or not isinstance(node.get('depends_on'), list)
            or len(node['depends_on']) != 1):
        return False
    predecessor = next(
        (row for row in plan.get('nodes', ())
         if isinstance(row, dict) and row.get('id') == node['depends_on'][0]), None,
    )
    data = node.get('input')
    parent_input = predecessor.get('input') if predecessor is not None else None
    return (
        predecessor is not None
        and predecessor.get('capability_id') == 'task.account'
        and isinstance(parent_input, dict)
        and parent_input.get('service') == 'gmail'
        and parent_input.get('operation') == 'list_unread'
        and not predecessor.get('depends_on')
        and isinstance(data, dict)
        and data.get('service') == 'gmail'
        and data.get('operation') == 'read_message'
        and type(data.get('index')) is int
        and 1 <= data['index'] <= 20
        and set(data) == {'service', 'operation', 'index'}
    )


def validate_dependent_account_attempt(
    state: dict, selection: NodeCandidate, *, attempt: int,
) -> dict:
    """Admit only one first-attempt Gmail list→indexed message read.

    The exact accepted and projected source is separately verified by the
    durable predecessor binding before provider execution and Core CAS.
    """
    if type(attempt) is not int or attempt != 1:
        raise PlanFenceError('Dependent account requires a fresh first attempt.')
    node = revalidate(state, selection)
    if (not supported_gmail_indexed_dependency(state['goal_plan'], node)
            or selection not in ready_read_only_candidates(
                state, owner=selection.owner, job_id=selection.job_id,
            )):
        raise PlanFenceError('Dependent Gmail read requires accepted list evidence.')
    return node


def revision_reuse_candidates(state: dict, revised_plan: dict) -> tuple[str, ...]:
    """Return structurally unchanged node IDs, *not* verified finished steps.

    Completion evidence and approval must be reverified by Core separately.
    No worker can be skipped solely on this result.
    """
    current = goal_state.validate(state)
    previous = current.get('goal_plan')
    if goal_state.authority(current) != 'canonical' or not isinstance(previous, dict):
        raise PlanFenceError('Canonical önceki plan gerekli.')
    proposed = goal_state.validate_goal_plan(revised_plan)
    if proposed['plan_version'] != previous['plan_version'] + 1:
        raise PlanFenceError('Plan revizyonu sürümü sıralı değil.')
    old = fingerprints(previous)
    new = fingerprints(proposed)
    return tuple(node['id'] for node in proposed['nodes']
                 if old.get(node['id']) == new[node['id']])
