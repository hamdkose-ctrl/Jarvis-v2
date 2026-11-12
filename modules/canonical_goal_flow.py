"""BRAIN-07: typed-goal admission and verified written completion.

This is a narrow adapter to the existing task planner, canonical Core, and one
Scheduler. A model proposes a DAG; it never grants permission or completion.
Only first-attempt, manifest-verified read-only tasks enter this lane.
"""
from __future__ import annotations

import copy
import hashlib
import json
import threading
import time

import release_guard
from modules import (
    canonical_plan_evidence, completion_policy,
    execution_record, goal_executor,
    goal_job_control, goal_plan_gate, goal_state, goal_state_compat,
    goal_state_store, llm, model_wait, task_agents, task_tools,
)

_COMPLETING = set()
_RECHECK = set()
_COMPLETING_LOCK = threading.Lock()
_READ_ONLY = frozenset({'research', 'account'})


def _canonical_plan(tasks):
    """Adapt the EXISTING task_agents planner's validated DAG proposal."""
    if not isinstance(tasks, list) or not 1 <= len(tasks) <= 8:
        raise ValueError('Canonical tasks are invalid.')
    nodes = []
    for task in tasks:
        kind = task['agent']
        deps = task.get('depends', [])
        if kind not in _READ_ONLY or (deps and kind != 'research'):
            raise ValueError('Only supported read-only task nodes may be admitted.')
        manifest = goal_plan_gate._read_only_manifest('task.' + kind)
        if manifest is None:
            raise ValueError('Capability has no read-only execution manifest.')
        data = task_tools.validate_input(kind, task['input'])
        nodes.append({
            'id': task['id'], 'depends_on': copy.deepcopy(deps),
            'capability_id': 'task.' + kind, 'input': data,
            'expected_output': 'Verified read-only task result',
            'acceptance': 'Domain-verified and Core-accepted WorkerResult evidence',
        })
    plan = {'plan_version': 1, 'nodes': nodes}
    return goal_state.validate_goal_plan(plan)


def try_create(owner: str, request_id: str, text: str):
    """Return (job_id, reply) only for an admissible typed read-only proposal.

    Unsupported/effectful proposals return None to the established legacy
    permission path. No worker or resource claim is made during planning.
    """
    if not isinstance(text, str) or not text.strip() or len(text) > 20000:
        return None
    if not isinstance(request_id, str) or not request_id.strip():
        return None

    # Same planner used by task_agents for its multi-node task format. No
    # duplicate free-text classifier, model/router, or autonomous capability.
    system = (
        task_agents._SYSTEM +
        '\nBu tur canonical arka plan araştırma önerisidir. Yalnız research '
        've salt-okunur account görevleri öner; desteklenmeyen etkiyi planlama. '
        'Kullanıcının istediği kapsamı karşılayamıyorsan uydurma kaynak verme.'
    )
    token = llm._key_context.set(owner)
    try:
        raw = model_wait.ask(text, system=system, max_tokens=2200, seconds=60)
    finally:
        llm._key_context.reset(token)
    try:
        proposed = task_agents._json(raw)
        tasks = task_agents.validate(proposed['tasks'])
        plan = _canonical_plan(tasks)
    except (KeyError, TypeError, ValueError):
        return None

    job_id = hashlib.sha256(
        (owner + '\x00' + request_id).encode('utf-8')
    ).hexdigest()[:16]
    root = goal_executor._root(owner)
    record_path = execution_record.path_for(root, job_id)
    state_path = root / (job_id + '.goalstate.json')
    with goal_job_control.locked(root, job_id):
        if record_path.exists() or state_path.exists():
            # The same client request may be handed off twice; only its exact
            # previously published owner/request may be acknowledged again.
            if not record_path.is_file() or not state_path.is_file():
                raise ValueError('Incomplete canonical publication requires review.')
            existing = execution_record.load(root, owner, job_id)
            state = goal_state_store.load(state_path)
            if (existing.get('request_id') != request_id
                    or existing.get('request') != text
                    or state['owner'] != owner or state['job_id'] != job_id
                    or goal_state.authority(state) != 'canonical'
                    or not isinstance(state.get('goal_plan'), dict)):
                raise ValueError('Canonical request identity collision or incomplete publication.')
            return job_id, 'Bu araştırma isteği zaten kayıtlı; ikinci kez başlatılmadı.'

        job = {
            'id': job_id, 'owner': owner, 'request_id': request_id,
            'request': text, 'created': time.time(), 'updated': time.time(),
            'state': 'running',
            'goals': [{'text': text, 'state': 'pending', 'evidence': []}],
            'steps': [{
                'id': row['id'], 'goal': 0,
                'tool': row['capability_id'].removeprefix('task.'),
                'input': copy.deepcopy(row['input']),
                'depends': list(row['depends_on']), 'state': 'queued',
                'started': False, 'attempts': 0,
            } for row in plan['nodes']],
            'outputs': {},
        }
        # Publish the born-canonical, already Core-planned state through the
        # authorized compat adapter. The second (execution) file is NOT atomic
        # with it; the existing Scheduler refuses an unmatched pair.
        saved = goal_state_compat.create_canonical_planned_goal(
            state_path, owner=owner, job_id=job_id, goal=text, plan=plan,
        )
        goal_plan_gate.ready_read_only_candidates(
            saved, owner=owner, job_id=job_id,
        )
        release_guard.atomic(record_path, execution_record.encode(job))
    # Do not move the legacy latest-pointer: it would turn an independent
    # canonical job into the blocking foreground legacy single-goal target.
    return job_id, 'Araştırma arka plana alındı. Diğer isteklerini yazabilirsin.'


def _semantic_proposal(owner: str, job: dict, node_ids: tuple[str, ...]):
    """Use the existing goal executor JSON/complete protocol, not worker status."""
    evidence = [{
        'id': step['id'], 'tool': step['tool'],
        'input': step['input'],
        'output': str(job['outputs'][step['id']].get('text', ''))[:1600],
    } for step in job['steps']]
    prompt = json.dumps({
        'request': job['request'], 'goals': job['goals'],
        'verified_steps': evidence,
        'required_evidence': list(node_ids),
    }, ensure_ascii=False)
    system = (
        goal_executor.SYSTEM +
        '\nBu turda bütün DAG adımlarının Core kanıtı vardır. Yalnız '
        '{"action":"complete","goal":0,"evidence":[...]} önerisini, '
        'kullanıcı isteği somut olarak karşılandıysa döndür. '
        'Yetersizse {"action":"ask","question":"..."} döndür. '
        'Yalnız gerçekten doğrulanmış node kimliklerini kullan; '
        'araç çalıştırma veya yeniden planlama önerme.'
    )
    token = llm._key_context.set(owner)
    try:
        answer = model_wait.ask(
            prompt, system=system, max_tokens=1200, seconds=60,
            validator=goal_executor._parse,
        )
    finally:
        llm._key_context.reset(token)
    return goal_executor._parse(answer)


def _complete_once(owner: str, job_id: str, notify) -> bool:
    """Attempt only one evidence-verified Core completion and event delivery."""
    try:
        proof = canonical_plan_evidence.certify_projected_plan(owner, job_id)
    except (canonical_plan_evidence.PlanEvidenceError, ValueError, OSError):
        return False
    root = goal_executor._owner_root(owner)
    with goal_job_control.locked(root, job_id):
        job = execution_record.load(root, owner, job_id)
        if (goal_job_control.fingerprint(job) != proof.record_digest
                or job.get('state') != 'running' or job.get('_canonical_delivery')):
            return False
    node_ids = tuple(node_id for node_id, _ in proof.output_digests)
    try:
        proposal = _semantic_proposal(owner, job, node_ids)
    except Exception:
        # A model/provider failure never becomes a successful Goal.
        return False
    if (proposal.get('action') != 'complete'
            or type(proposal.get('goal')) is not int
            or proposal['goal'] != 0
            or not isinstance(proposal.get('evidence'), list)
            or len(proposal['evidence']) != len(node_ids)
            or set(proposal['evidence']) != set(node_ids)):
        return False
    if len(job['goals']) != 1:
        return False
    decision = completion_policy.evaluate_evidence(
        goal_executor._check_news_completion,
        job, job['goals'][0], list(node_ids), final=True,
    )
    if decision['decision'] != completion_policy.COMPLETE:
        return False

    state_path = root / (job_id + '.goalstate.json')
    record_path = execution_record.path_for(root, job_id)
    with goal_job_control.locked(root, job_id):
        state = goal_state_store.load(state_path)
        current = execution_record.load(root, owner, job_id)
        if (state['owner'] != owner or state['job_id'] != job_id
                or state['version'] != proof.goal_version
                or goal_job_control.fingerprint(current) != proof.record_digest
                or state['state'] not in ('running', 'pending')):
            return False
        completed = copy.deepcopy(current)
        completed['goals'][0].update(
            state='done', evidence=list(node_ids),
        )
        completed['state'] = 'done'
        completed['_canonical_delivery'] = 'reserved'
        completed['updated'] = time.time()
        # Keep the Core CAS and proof/journal fence inside its authorized
        # compat commit adapter. A journal 'done' cannot precede Core success.
        goal_state_compat.commit_verified_goal_completion(
            state_path, owner=owner, job_id=job_id, proof=proof,
        )
        release_guard.atomic(record_path, execution_record.encode(completed))
    message = goal_executor.render(completed)
    try:
        notify(owner, job_id, message)
    except Exception:
        # Could have reached one sink already. Never resend blindly.
        return False
    with goal_job_control.locked(root, job_id):
        saved = execution_record.load(root, owner, job_id)
        if saved.get('_canonical_delivery') == 'reserved':
            saved['_canonical_delivery'] = 'delivered'
            saved['updated'] = time.time()
            release_guard.atomic(record_path, execution_record.encode(saved))
    return True


def complete_and_deliver(owner: str, job_id: str, notify) -> bool:
    """Serialize completion per goal; coalesce racing accepted worker wakeups.

    A second root can finish while the first completion callback is verifying
    an earlier projection. Its wake cannot be dropped: mark one bounded recheck
    on the same callback owner, without a second scheduler or global lock.
    """
    if not callable(notify):
        raise ValueError('Canonical delivery sink is required.')
    key = (owner, job_id)
    with _COMPLETING_LOCK:
        if key in _COMPLETING:
            _RECHECK.add(key)
            return False
        _COMPLETING.add(key)
    try:
        while True:
            result = _complete_once(owner, job_id, notify)
            with _COMPLETING_LOCK:
                again = key in _RECHECK and not result
                _RECHECK.discard(key)
                if not again:
                    _COMPLETING.discard(key)
                    return result
    finally:
        with _COMPLETING_LOCK:
            _COMPLETING.discard(key)
            _RECHECK.discard(key)
