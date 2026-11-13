"""BRAIN-07: typed-goal admission and verified written completion.

This is a narrow adapter to the existing task planner, canonical Core, and one
Scheduler. A model proposes a DAG; it never grants permission or completion.
Only first-attempt, manifest-verified read-only tasks enter this lane.
"""
from __future__ import annotations

import copy
from dataclasses import replace
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
    goal_state_store, llm, model_wait, requests_state, task_agents, task_tools,
)

_COMPLETING = set()
_RECHECK = set()
_COMPLETING_LOCK = threading.Lock()
_READ_ONLY = frozenset({'research', 'account', 'verify'})
_RESULT_QUERY = re.compile(r'hedef sonucu\s+([a-f0-9]{16})\s*[.!?]?\Z', re.IGNORECASE)
_REPLY_QUERY = re.compile(r'hedef cevap\s+([a-f0-9]{16})\s+(.{1,2000})\Z', re.IGNORECASE | re.DOTALL)


def _canonical_plan(tasks):
    """Adapt the EXISTING task_agents planner's validated DAG proposal."""
    if not isinstance(tasks, list) or not 1 <= len(tasks) <= 8:
        raise ValueError('Canonical tasks are invalid.')
    nodes = []
    for task in tasks:
        kind = task['agent']
        deps = task.get('depends', [])
        if kind not in _READ_ONLY:
            raise ValueError('Only supported read-only task nodes may be admitted.')
        if kind == 'verify':
            # Only a first-attempt, no-effect verification of existing
            # research/account results; writer remains outside this lane.
            parents = [next((p for p in tasks if p['id'] == dep), None)
                       for dep in deps]
            if (not 1 <= len(deps) <= 6 or any(
                    not isinstance(p, dict)
                    or p.get('agent') not in ('research', 'account')
                    for p in parents)):
                raise ValueError('Verify requires read-only predecessor nodes.')
        if deps and kind not in ('research', 'verify'):
            # Developer-approved, exact Gmail chain only: a verified unread
            # list can select ONE message by index. No arbitrary account DAG.
            source = next((row for row in tasks if row['id'] == deps[0]), None) if len(deps) == 1 else None
            if (kind != 'account' or not isinstance(source, dict)
                    or source.get('agent') != 'account'
                    or source.get('input', {}).get('service') != 'gmail'
                    or source['input'].get('operation') != 'list_unread'
                    or task.get('input', {}).get('service') != 'gmail'
                    or task['input'].get('operation') != 'read_message'
                    or type(task['input'].get('index')) is not int
                    or set(task['input']) != {'service', 'operation', 'index'}):
                raise ValueError('Only verified Gmail list→indexed read is supported.')
        if (kind == 'account' and not deps
                and task['input'].get('service') == 'gmail'
                and task['input'].get('operation') == 'read_message'
                and 'index' in task['input']):
            # A new canonical request has no implicit, owner-bound mail list.
            # Unqualified list indices must never select provider messages.
            raise ValueError('Gmail indexed read requires one verified list dependency.')
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
        # A duplicate can have been cancelled while waiting for the first
        # planner. Recheck AFTER OS-lock acquisition as well (cross-process).
        requests_state.check()
        if planning_path.is_symlink() or planning_path.with_suffix(
                planning_path.suffix + '.lock').is_symlink():
            raise ValueError('Canonical planner control path must not be a symlink.')
        with goal_state_store._exclusive(planning_path):
            requests_state.check()
            yield


_LEGACY_ADMISSION_SCHEMA = 'jarvis.canonical_legacy_admission.v1'


def _legacy_admission_path(root, job_id):
    return root / (job_id + '.planning')


def _legacy_admission_identity(owner, request_id, text, job_id):
    # Owner namespace, request ID and exact user text are bound without
    # persisting raw request content in an additional file.
    expected_id = hashlib.sha256(
        (owner + '\x00' + request_id).encode('utf-8')
    ).hexdigest()[:16]
    if expected_id != job_id:
        raise ValueError('Canonical admission request identity differs.')
    return {
        'schema': _LEGACY_ADMISSION_SCHEMA,
        'job_id': job_id,
        'request_sha256': hashlib.sha256(
            (owner + '\x00' + request_id).encode('utf-8')
        ).hexdigest(),
        'text_sha256': hashlib.sha256(text.encode('utf-8')).hexdigest(),
        'result': 'legacy_claimed',
    }


def _legacy_admitted(root, owner, request_id, text, job_id):
    """Durable one-shot fallback receipt, NOT a second Goal/worker store.

    The outer per-request planning gate owns the .planning.lock OS lock.
    An unreadable, changed or foreign receipt is never interpreted as new.
    """
    path = _legacy_admission_path(root, job_id)
    if path.is_symlink():
        raise ValueError('Legacy admission receipt cannot be a symlink.')
    if not path.exists():
        return False
    if not path.is_file() or path.stat().st_size > 2048:
        raise ValueError('Legacy admission receipt is invalid.')
    try:
        receipt = json.loads(path.read_text(encoding='utf-8'))
    except (UnicodeError, ValueError) as exc:
        raise ValueError('Legacy admission receipt is unreadable.') from exc
    if receipt != _legacy_admission_identity(owner, request_id, text, job_id):
        raise ValueError('Legacy admission identity collision or corruption.')
    return True


def _claim_legacy_once(root, owner, request_id, text, job_id):
    if _legacy_admitted(root, owner, request_id, text, job_id):
        raise ValueError('Legacy handoff already claimed.')
    path = _legacy_admission_path(root, job_id)
    receipt = _legacy_admission_identity(owner, request_id, text, job_id)
    # The receipt precedes the first legacy execution. Crash before execution
    # is a conservative blocked retry, never a license to replay the effect.
    release_guard.atomic(path, json.dumps(
        receipt, ensure_ascii=False, sort_keys=True,
    ).encode('utf-8'))


def _legacy_duplicate_reply():
    return (
        None,
        'Bu istek kimliği daha önce eski hedef yürütücüsüne devredildi; '
        'ikinci kez çalıştırılmadı. İlk çalıştırmanın sonucu burada '
        'doğrulanmadı; hedef durumunu ayrı kontrol et.',
    )


def try_create(owner: str, request_id: str, text: str, *, legacy_plan_sink=None):
    """Admit one request ID to canonical or one-shot legacy fallback.

    An unsupported first plan returns None only AFTER a durable single
    fallback claim. Subsequent identical attempts return a no-op reply.
    No worker is authorized by the planner or this receipt.
    """
    if legacy_plan_sink is not None and not callable(legacy_plan_sink):
        raise TypeError('Legacy plan sink must be callable.')
    if not isinstance(text, str) or not text.strip() or len(text) > 20000:
        return None
    if not isinstance(request_id, str) or not request_id.strip():
        # An uncorrelated request must not silently allocate a legacy UUID.
        raise ValueError('Canonical typed request ID is required.')

    job_id = hashlib.sha256(
        (owner + '\x00' + request_id).encode('utf-8')
    ).hexdigest()[:16]
    root = goal_executor._root(owner)
    # The per-request planning gate is independent of Core/Scheduler locks,
    # and is held only for this request's one admission/planning window.
    with _planning_once(root, job_id):
        return _try_create_planned(owner, request_id, text, job_id, root,
                                   legacy_plan_sink=legacy_plan_sink)


def _try_create_planned(owner: str, request_id: str, text: str, job_id: str, root,
                        *, legacy_plan_sink=None):
    # Ordinary client retries must not spend model tokens.
    with goal_job_control.locked(root, job_id):
        prior = _existing_request(root, owner, job_id, request_id, text)
        receipt = _legacy_admitted(root, owner, request_id, text, job_id)
        if prior is not None and receipt:
            raise ValueError('Canonical and legacy admission cannot coexist.')
        if prior is not None:
            return prior
        if receipt:
            return _legacy_duplicate_reply()

    # Same planner used by task_agents for its multi-node task format. No
    # duplicate free-text classifier, model/router, or autonomous capability.
    system = (
        task_agents._SYSTEM +
        '\nBu tur canonical arka plan araştırma önerisidir. Yalnız research '
        've salt-okunur account görevleri öner; kanıtları birleştirmek '
        'için yalnız doğrulanmış research/account bağımlı verify görevini kullan. '
        'Writer dosyaya yazdığı için canonical salt-okunur kapsamda değildir. '
        'Desteklenmeyen etkiyi planlama. '
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
        # Unsupported/invalid FIRST planner decision is still a decision
        # for this request ID. Persist its one-shot legacy handoff before
        # returning None so a concurrent/restarted duplicate cannot launch
        # a different canonical plan while legacy might be effectful.
        requests_state.check()
        with goal_job_control.locked(root, job_id):
            prior = _existing_request(root, owner, job_id, request_id, text)
            if prior is not None:
                return prior
            _claim_legacy_once(root, owner, request_id, text, job_id)
        # Reuse the SAME first proposal only when the legacy executor's
        # strict parser deems it replay-safe. This transfers no permission.
        if legacy_plan_sink is not None and isinstance(locals().get('tasks'), list):
            try:
                safe_call = goal_executor._parse(json.dumps(
                    {'tasks': tasks}, ensure_ascii=False,
                ))
            except (KeyError, TypeError, ValueError):
                pass
            else:
                legacy_plan_sink(copy.deepcopy(safe_call))
        return None

    record_path = execution_record.path_for(root, job_id)
    state_path = root / (job_id + '.goalstate.json')
    with goal_job_control.locked(root, job_id):
        # A timed-out provider response or a cancellation cannot publish
        # new work after the request has been stopped.
        requests_state.check()
        prior = _existing_request(root, owner, job_id, request_id, text)
        receipt = _legacy_admitted(root, owner, request_id, text, job_id)
        if prior is not None and receipt:
            raise ValueError('Canonical and legacy admission cannot coexist.')
        if prior is not None:
            return prior
        if receipt:
            return _legacy_duplicate_reply()

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
        'user_clarification': (
            {'question': job['_canonical_dialog']['question'],
             'answer': job['_canonical_dialog']['answer']}
            if isinstance(job.get('_canonical_dialog'), dict)
               and job['_canonical_dialog'].get('state') == 'answered'
            else None
        ),
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


def _accepted_user_channel(receipt) -> str | None:
    """Return an acknowledged owner-facing sink, never log-only success.

    The channel reported sink acceptance, NOT human read/open and NOT an
    end-to-end exactly-once transport guarantee. Other channel failures do
    not erase an already accepted owner-visible delivery.
    """
    if not isinstance(receipt, dict):
        return None
    for channel in ('ui', 'ntfy'):
        if receipt.get(channel) == 'delivered':
            return channel
    return None


def _ask_for_clarification(owner: str, job_id: str, proof, question: str, notify) -> None:
    """Persist one owner-bound pending question; never mark Goal done or replay a worker.

    A question is reserved before fanout. Unknown external delivery is NEVER
    auto-replayed, but its text remains readable through goal status. The
    user answers with a bounded explicit job-ID protocol, not an NL classifier.
    """
    if not isinstance(question, str) or not question.strip() or len(question) > 600:
        return
    from modules import runtime_worker_result
    runtime_worker_result.require_scheduler_active()
    root = goal_executor._owner_root(owner)
    record_path = execution_record.path_for(root, job_id)
    state_path = root / (job_id + '.goalstate.json')
    with goal_job_control.locked(root, job_id):
        runtime_worker_result.require_scheduler_active()
        state = goal_state_store.load(state_path)
        current = execution_record.load(root, owner, job_id)
        if (state['owner'] != owner or state['job_id'] != job_id
                or state['state'] not in ('pending', 'running')
                or state['version'] != proof.goal_version
                or current.get('state') != 'running'
                or current.get('_canonical_delivery')
                or goal_job_control.fingerprint(current) != proof.record_digest):
            return
        previous = current.get('_canonical_dialog')
        if previous is not None and (not isinstance(previous, dict)
                                    or previous.get('state') != 'answered'):
            return
        round_number = 1 if previous is None else previous.get('round', 0) + 1
        if type(round_number) is not int or not 1 <= round_number <= 3:
            return
        event_id = f'canonical-question:{job_id}:{round_number}'
        current['_canonical_dialog'] = {
            'state': 'waiting', 'question': question.strip(),
            'round': round_number, 'event_id': event_id,
            'delivery': 'reserved', 'created': time.time(),
        }
        release_guard.atomic(record_path, execution_record.encode(current))
    message = ('Bu hedefi tamamlamak için ek bilgi gerekiyor: ' + question.strip()
               + f'\nYanıtlamak için: hedef cevap {job_id} <yanıt>')
    runtime_worker_result.require_scheduler_active()
    try:
        receipt = notify(owner, job_id, message)
    except Exception:
        _record_failure('modules/canonical_goal_flow.py:question_delivery')
        return
    accepted_channel = _accepted_user_channel(receipt)
    if accepted_channel is None:
        return
    with goal_job_control.locked(root, job_id):
        current = execution_record.load(root, owner, job_id)
        dialog = current.get('_canonical_dialog')
        if (isinstance(dialog, dict) and dialog.get('event_id') == event_id
                and dialog.get('state') == 'waiting'
                and dialog.get('delivery') == 'reserved'):
            dialog['delivery'] = accepted_channel + '_accepted'
            evidence = {
                'event_id': event_id, 'channel': accepted_channel,
                'status': 'accepted', 'recorded_at': time.time(),
            }
            dialog['delivery_receipt'] = evidence
            if accepted_channel == 'ui':
                dialog['ui_receipt'] = evidence
            release_guard.atomic(record_path, execution_record.encode(current))


def submit_clarification(owner: str, job_id: str, answer: str) -> str:
    """Durably answer an existing question; only the one Scheduler may resume."""
    from modules import requests_state, goal_state
    requests_state.check()
    if (not isinstance(answer, str) or not answer.strip()
            or len(answer) > 2000):
        raise ValueError('Hedef cevabı boş veya çok uzun.')
    root = goal_executor._owner_root(owner)
    record_path = execution_record.path_for(root, job_id)
    with goal_job_control.locked(root, job_id):
        state = goal_state_store.load(root / (job_id + '.goalstate.json'))
        if ((state['owner'], state['job_id']) != (owner, job_id)
                or goal_state.authority(state) != 'canonical'
                or not isinstance(state.get('goal_plan'), dict)
                or state['state'] not in ('pending', 'running')):
            raise ValueError('Hedef artık açıklama kabul etmiyor.')
        current = execution_record.load(root, owner, job_id)
        dialog = current.get('_canonical_dialog')
        if (current.get('state') != 'running'
                or current.get('_canonical_delivery')
                or not isinstance(dialog, dict)
                or dialog.get('state') != 'waiting'
                or not isinstance(dialog.get('question'), str)
                or not dialog.get('question').strip()):
            raise ValueError('Bu hedefin açık bir kullanıcı sorusu bulunmuyor.')
        updated = copy.deepcopy(current)
        updated['_canonical_dialog']['state'] = 'answered'
        updated['_canonical_dialog']['answer'] = answer.strip()
        updated['_canonical_dialog']['answered_at'] = time.time()
        release_guard.atomic(record_path, execution_record.encode(updated))
    return ('Yanıt bu hedefe kaydedildi. Var olan kanıtlar korunuyor; '
            'Scheduler tamamlanma kararını yeniden değerlendirecek, '
            'hiçbir worker tekrar başlatılmadı.')


def delivery_metadata(owner: str, job_id: str) -> tuple[str, str, str]:
    """Read one durable notification identity for the existing event sink."""
    root = goal_executor._owner_root(owner)
    with goal_job_control.locked(root, job_id):
        state = goal_state_store.load(root / (job_id + '.goalstate.json'))
        current = execution_record.load(root, owner, job_id)
        if (state['owner'], state['job_id']) != (owner, job_id):
            raise PermissionError('Bildirim sahibi eşleşmiyor.')
        dialog = current.get('_canonical_dialog')
        if (current.get('state') == 'running'
                and state['state'] in ('pending', 'running')
                and isinstance(dialog, dict)
                and dialog.get('state') == 'waiting'
                and dialog.get('delivery') == 'reserved'
                and isinstance(dialog.get('event_id'), str)):
            return 'question', dialog['event_id'], 'Jarvis hedef sorusu'
        if (current.get('state') == 'done'
                and state['state'] == 'done'
                and current.get('_canonical_delivery') == 'reserved'
                and current.get('_canonical_result_event_id') == 'canonical:' + job_id):
            return 'completed', 'canonical:' + job_id, 'Jarvis araştırma sonucu'
    raise ValueError('Doğrulanmış bekleyen bildirimin kimliği bulunamadı.')


def _complete_once(owner: str, job_id: str, notify) -> bool:
    """Attempt only one evidence-verified Core completion and event delivery."""
    from modules import runtime_worker_result
    runtime_worker_result.require_scheduler_active()
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
    dialog = job.get('_canonical_dialog')
    if dialog is not None and (
            not isinstance(dialog, dict)
            or dialog.get('state') != 'answered'
            or not isinstance(dialog.get('answer'), str)
            or not dialog['answer'].strip()):
        # A waiting question is not a fresh model prompt after restart.
        return False
    node_ids = tuple(node_id for node_id, _ in proof.output_digests)
    try:
        proposal = _semantic_proposal(owner, job, node_ids)
    except Exception:
        _record_failure('modules/canonical_goal_flow.py:semantic_completion')
        # A model/provider failure never becomes a successful Goal.
        return False
    # The model may have finished after stop/deadline. Its proposed success
    # does not grant a terminal Core transition or a new user question.
    runtime_worker_result.require_scheduler_active()
    if proposal.get('action') == 'ask':
        _ask_for_clarification(owner, job_id, proof, proposal.get('question'), notify)
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
        runtime_worker_result.require_scheduler_active()
        state = goal_state_store.load(state_path)
        current = execution_record.load(root, owner, job_id)
        if (state['owner'] != owner or state['job_id'] != job_id
                or state['version'] != proof.goal_version
                or goal_job_control.fingerprint(current) != proof.record_digest
                or state['state'] not in ('running', 'pending')):
            return False
        # A crash between terminal Core CAS and this second JSON file must
        # not permanently erase the verified written result. Freeze ONLY its
        # display bytes and event identity in the still-running journal before
        # the terminal CAS. No 'done' flag or delivery authorization exists yet.
        # This pre-commit record is not a second GoalState or an outbox.
        prepared = copy.deepcopy(current)
        prepared['_canonical_result_text'] = message
        prepared['_canonical_result_event_id'] = 'canonical:' + job_id
        prepared['updated'] = time.time()
        release_guard.atomic(record_path, execution_record.encode(prepared))
        # The original proof already certified every accepted output and
        # checked both snapshots; under the SAME job lock, the only journal
        # changes above were our frozen result metadata and updated timestamp.
        # Bind its new exact fingerprint before the existing Core adapter CAS.
        prepared_proof = replace(
            proof, record_digest=goal_job_control.fingerprint(prepared),
        )
        goal_state_compat.commit_verified_goal_completion(
            state_path, owner=owner, job_id=job_id, proof=prepared_proof,
        )
        # The terminal state is now Core-authorized. Recording the outcome and
        # reserved delivery may fail on disk: an owner-only READ of the frozen
        # pre-CAS result remains possible after verifying terminal Core proof.
        completed = copy.deepcopy(prepared)
        completed['goals'][0].update(
            state='done', evidence=list(node_ids),
        )
        completed['state'] = 'done'
        completed['_canonical_delivery'] = 'reserved'
        completed['updated'] = time.time()
        release_guard.atomic(record_path, execution_record.encode(completed))
    runtime_worker_result.require_scheduler_active()
    try:
        receipt = notify(owner, job_id, message)
    except Exception:
        _record_failure('modules/canonical_goal_flow.py:result_delivery')
        # Could have reached one sink already. Never resend blindly.
        return False
    # Log-only success is not user delivery; UI or user-configured ntfy
    # acceptance is recorded separately from user read/open acknowledgments.
    accepted_channel = _accepted_user_channel(receipt)
    if accepted_channel is None:
        return False
    with goal_job_control.locked(root, job_id):
        saved = execution_record.load(root, owner, job_id)
        if saved.get('_canonical_delivery') == 'reserved':
            saved['_canonical_delivery'] = 'delivered'
            evidence = {
                'event_id': 'canonical:' + job_id,
                'channel': accepted_channel,
                'status': 'accepted', 'recorded_at': time.time(),
            }
            saved['_canonical_delivery_receipt'] = evidence
            if accepted_channel == 'ui':
                saved['_canonical_ui_receipt'] = evidence
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
                or journal.get('request') != state['goal']
                or not isinstance(goals, list) or len(goals) != 1
                or not isinstance(steps, list) or not isinstance(outputs, dict)):
            raise ValueError('Only verified completed canonical result may be read.')
        node_ids = tuple(node['id'] for node in plan['nodes'])
        evidence = goals[0].get('evidence')
        finished = (
            journal.get('state') == 'done'
            and journal.get('_canonical_delivery') in ('reserved', 'delivered')
            and goals[0].get('state') == 'done'
            and isinstance(evidence, list)
            and len(evidence) == len(node_ids)
            and set(evidence) == set(node_ids)
        )
        torn_after_core_cas = (
            journal.get('state') == 'running'
            and journal.get('_canonical_delivery') is None
            and journal.get('_canonical_result_event_id') == 'canonical:' + job_id
            and goals[0].get('state') == 'pending'
            and evidence == []
        )
        if (not (finished or torn_after_core_cas)
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
        if torn_after_core_cas:
            # Never trust a cached but uncommitted string on its own. Prove
            # the terminal Core transition AND every exact accepted output,
            # then recompute the original deterministic completed rendering.
            # A forged/missing frozen string is rejected; no disk mutation,
            # worker retry or second notification is authorized by a read.
            preview = copy.deepcopy(journal)
            preview['goals'][0].update(
                state='done', evidence=list(node_ids),
            )
            preview['state'] = 'done'
            if (not isinstance(result, str) or not result.strip()
                    or goal_executor.render(preview) != result):
                raise ValueError('Frozen completion result could not be verified.')
        elif not isinstance(result, str) or not result.strip():
            # Older completed journal without the new frozen result snapshot.
            result = goal_executor.render(journal)
        if not isinstance(result, str) or not result.strip():
            raise ValueError('Completed result is unreadable.')
    note = ('\n\nSonuç Core tarafından tamamlandı; ikinci kayıt kesintiye uğramış '
            'olabilir. Otomatik bildirim tekrar gönderilmedi.'
            if torn_after_core_cas else
            '\n\nBu sorgu bildirim göndermez veya işi tekrar çalıştırmaz.')
    return f'Kayıtlı hedef sonucu — {job_id}:\n\n' + result + note


def read_result_command(owner: str, text: str) -> str | None:
    """Bounded exact-ID result read or user answer; never an NL classifier."""
    if not isinstance(text, str):
        return None
    reply = _REPLY_QUERY.fullmatch(text.strip())
    if reply is not None:
        try:
            return submit_clarification(owner, reply.group(1).lower(), reply.group(2))
        except (FileNotFoundError, ValueError, PermissionError, OSError, TypeError, KeyError):
            return 'Bu hedef açıklama kabul etmiyor; başka hedefe veya workera dokunulmadı.'
    match = _RESULT_QUERY.fullmatch(text.strip())
    if match is None:
        return None
    try:
        return read_completed_result(owner, match.group(1).lower())
    except (FileNotFoundError, ValueError, PermissionError, OSError, TypeError, KeyError):
        # New queued first-plan records use the SAME owner-bound GoalState and
        # ExecutionRecord, but are intentionally not completed results.
        # A status query is read-only and can never dispatch the model again.
        from modules import canonical_planning_queue
        pending = canonical_planning_queue.status(owner, match.group(1).lower())
        if pending is not None:
            return pending
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
