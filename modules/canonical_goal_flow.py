"""BRAIN-07: typed-goal admission and verified written completion.

This is a narrow adapter to the existing task planner, canonical Core, and one
Scheduler. A model proposes a DAG; it never grants permission or completion.
Only first-attempt, manifest-verified read-only tasks enter this lane.
"""
from __future__ import annotations

import copy
from contextlib import contextmanager
import hashlib
import json
import re
import threading
import time
from weakref import WeakValueDictionary

import release_guard
from modules.diagnostics import record_failure as _record_failure
from modules import (
    canonical_output_projection, canonical_plan_evidence, completion_policy,
    execution_record, goal_executor,
    goal_job_control, goal_plan_gate, goal_state, goal_state_compat,
    goal_state_store, llm, model_wait, task_agents, task_tools,
)

_COMPLETING = set()
_RECHECK = set()
_COMPLETING_LOCK = threading.Lock()
_READ_ONLY = frozenset({'research', 'account'})
_RESULT_QUERY = re.compile(r'hedef sonucu\s+([a-f0-9]{16})\s*[.!?]?\Z', re.IGNORECASE)


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


def _existing_request(root, owner: str, job_id: str, request_id: str, text: str):
    """Find a published identity under the caller's existing per-job lock."""
    record_path = execution_record.path_for(root, job_id)
    state_path = root / (job_id + '.goalstate.json')
    if not (record_path.exists() or record_path.is_symlink()
            or state_path.exists() or state_path.is_symlink()):
        return None
    if (record_path.is_symlink() or state_path.is_symlink()
            or not record_path.is_file() or not state_path.is_file()):
        raise ValueError('Incomplete canonical publication requires review.')
    record = execution_record.load(root, owner, job_id)
    state = goal_state_store.load(state_path)
    if (record.get('request_id') != request_id or record.get('request') != text
            or state['owner'] != owner or state['job_id'] != job_id
            or state['goal'] != text.strip()
            or goal_state.authority(state) != 'canonical'
            or not isinstance(state.get('goal_plan'), dict)):
        raise ValueError('Canonical request identity collision or incomplete publication.')
    return (job_id, 'Bu araştırma isteği zaten kayıtlı; ikinci kez başlatılmadı. '
            f'Sonucu "hedef sonucu {job_id}" yazarak sorgulayabilirsin.')


# Only two callers for the SAME owner/request ID contend here. This is
# deliberately NOT the Core/Scheduler control lock: a provider can wait for
# up to 60 s without blocking other goals' state/worker CAS writes.
_PLAN_MUTEX_GUARD = threading.Lock()
_PLAN_MUTEXES = WeakValueDictionary()


@contextmanager
def _planning_once(root, job_id):
    """Serialize same-ID planner admission across threads and processes.

    A separate .planning.lock OS lock is used to protect multi-process
    admission. Other IDs do not share it; short Core control sections remain
    exclusively inside _try_create_planned.
    """
    planning_path = root / (job_id + '.planning')
    key = str(planning_path.absolute())
    with _PLAN_MUTEX_GUARD:
        mutex = _PLAN_MUTEXES.get(key)
        if mutex is None:
            mutex = threading.Lock()
            _PLAN_MUTEXES[key] = mutex
    with mutex:
        if planning_path.is_symlink() or planning_path.with_suffix(
                planning_path.suffix + '.lock').is_symlink():
            raise ValueError('Canonical planner control path must not be a symlink.')
        with goal_state_store._exclusive(planning_path):
            yield


def try_create(owner: str, request_id: str, text: str):
    """Return (job_id, reply) only for an admissible typed read-only proposal.

    Unsupported/effectful proposals return None to the established legacy
    permission path. No worker or resource claim is made during planning.
    """
    if not isinstance(text, str) or not text.strip() or len(text) > 20000:
        return None
    if not isinstance(request_id, str) or not request_id.strip():
        return None

    job_id = hashlib.sha256(
        (owner + '\x00' + request_id).encode('utf-8')
    ).hexdigest()[:16]
    root = goal_executor._root(owner)
    # The per-request planning gate is independent of Core/Scheduler locks,
    # and is held only for this request's one admission/planning window.
    with _planning_once(root, job_id):
        return _try_create_planned(owner, request_id, text, job_id, root)


def _try_create_planned(owner: str, request_id: str, text: str, job_id: str, root):
    # Ordinary client retries must not spend model tokens.
    with goal_job_control.locked(root, job_id):
        prior = _existing_request(root, owner, job_id, request_id, text)
        if prior is not None:
            return prior

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

    record_path = execution_record.path_for(root, job_id)
    state_path = root / (job_id + '.goalstate.json')
    with goal_job_control.locked(root, job_id):
        # Two concurrent copies can both plan; only one may publish.
        prior = _existing_request(root, owner, job_id, request_id, text)
        if prior is not None:
            return prior

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
    return (job_id, 'Araştırma arka plana alındı. Diğer isteklerini yazabilirsin. '
            f'Sonuç hazır olduğunda "hedef sonucu {job_id}" yazabilirsin.')



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
        _record_failure('modules/canonical_goal_flow.py:semantic_completion')
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

    # Prepare result text before declaring global completion. A render error
    # cannot strand a terminal goal with no written result to recover.
    preview = copy.deepcopy(job)
    preview['goals'][0].update(state='done', evidence=list(node_ids))
    preview['state'] = 'done'
    try:
        message = goal_executor.render(preview)
    except Exception:
        _record_failure('modules/canonical_goal_flow.py:completion_render')
        return False
    if not isinstance(message, str) or not message.strip():
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
        completed['_canonical_result_text'] = message
        completed['_canonical_result_event_id'] = 'canonical:' + job_id
        completed['updated'] = time.time()
        # Keep the Core CAS and proof/journal fence inside its authorized
        # compat commit adapter. A journal 'done' cannot precede Core success.
        goal_state_compat.commit_verified_goal_completion(
            state_path, owner=owner, job_id=job_id, proof=proof,
        )
        release_guard.atomic(record_path, execution_record.encode(completed))
    try:
        notify(owner, job_id, message)
    except Exception:
        _record_failure('modules/canonical_goal_flow.py:result_delivery')
        # Could have reached one sink already. Never resend blindly.
        return False
    with goal_job_control.locked(root, job_id):
        saved = execution_record.load(root, owner, job_id)
        if saved.get('_canonical_delivery') == 'reserved':
            saved['_canonical_delivery'] = 'delivered'
            saved['updated'] = time.time()
            release_guard.atomic(record_path, execution_record.encode(saved))
    return True


def read_completed_result(owner: str, job_id: str) -> str:
    """Read an owner-bound Core-completed result without a model or resend."""
    root = goal_executor._owner_root(owner)
    record_path = execution_record.path_for(root, job_id)
    state_path = root / (job_id + '.goalstate.json')
    if (not root.is_dir() or record_path.is_symlink() or state_path.is_symlink()
            or not record_path.is_file() or not state_path.is_file()):
        raise ValueError('Completed canonical result is not available.')
    with goal_job_control.locked(root, job_id):
        state = goal_state_store.load(state_path)
        journal = execution_record.load(root, owner, job_id)
        plan = state.get('goal_plan')
        goals = journal.get('goals')
        steps = journal.get('steps')
        outputs = journal.get('outputs')
        if ((state['owner'], state['job_id']) != (owner, job_id)
                or goal_state.authority(state) != 'canonical'
                or state['state'] != 'done'
                or state['audit'][-1]['reason_code'] != 'CANONICAL_SEMANTIC_COMPLETION_VERIFIED'
                or not isinstance(plan, dict)
                or journal.get('state') != 'done'
                or journal.get('request') != state['goal']
                or journal.get('_canonical_delivery') not in ('reserved', 'delivered')
                or not isinstance(goals, list) or len(goals) != 1
                or goals[0].get('state') != 'done'
                or not isinstance(steps, list) or not isinstance(outputs, dict)):
            raise ValueError('Only verified completed canonical result may be read.')
        node_ids = tuple(node['id'] for node in plan['nodes'])
        evidence = goals[0].get('evidence')
        if (not isinstance(evidence, list) or len(evidence) != len(node_ids)
                or set(evidence) != set(node_ids)
                or len(steps) != len(node_ids) or set(outputs) != set(node_ids)):
            raise ValueError('Completion journal differs from the accepted plan.')
        for node in plan['nodes']:
            matching = [step for step in steps
                        if isinstance(step, dict) and step.get('id') == node['id']]
            if (len(matching) != 1 or matching[0].get('state') != 'done'
                    or matching[0].get('tool') != node['capability_id'].removeprefix('task.')
                    or matching[0].get('input') != node['input']
                    or matching[0].get('depends') != node['depends_on']
                    or not isinstance(outputs[node['id']], dict)):
                raise ValueError('Completed step differs from accepted plan.')
            # Existing accepted Core hash/manifest/audit verifier, with only
            # its final authorized terminal transition ignored for READS.
            canonical_output_projection._accepted_row(
                state, owner, job_id, node, outputs[node['id']],
                allow_completed_read=True,
            )
        result = journal.get('_canonical_result_text')
        if not isinstance(result, str) or not result.strip():
            # Older completed journal without the new frozen result snapshot.
            result = goal_executor.render(journal)
        if not isinstance(result, str) or not result.strip():
            raise ValueError('Completed result is unreadable.')
    return (f'Kayıtlı hedef sonucu — {job_id}:\n\n' + result +
            '\n\nBu sorgu bildirim göndermez veya işi tekrar çalıştırmaz.')


def read_result_command(owner: str, text: str) -> str | None:
    """A bounded explicit result-ID protocol; never an NL intent classifier."""
    match = _RESULT_QUERY.fullmatch(text.strip()) if isinstance(text, str) else None
    if match is None:
        return None
    try:
        return read_completed_result(owner, match.group(1).lower())
    except (FileNotFoundError, ValueError, PermissionError, OSError, TypeError, KeyError):
        return ('Bu kimliğe ait doğrulanmış tamamlanmış sonuç henüz görüntülenemiyor. '
                'Hiçbir iş yeniden başlatılmadı ve bildirim tekrar gönderilmedi.')


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
