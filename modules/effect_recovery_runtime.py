"""Durable intent/reconcile bridge for provider-backed effects.

It records intent before an effect, never invokes an effect worker during
recovery, and sends only a reconciled done observation through WorkerResult
fencing and the existing Reducer/CAS commit path.
"""
from __future__ import annotations

import copy
import hashlib
import json

from modules import crash_recovery, effect_journal, runtime_worker_result, worker_result_hook


_FENCE = ('owner', 'job_id', 'step_id', 'command_id', 'attempt',
          'expected_job_version', 'capability_id', 'capability_version', 'input_digest')


class EffectReplayBlocked(effect_journal.ContractViolation):
    reason_code = 'EFFECT_REPLAY_BLOCKED'
    recovery_class = 'manual_review'


def required(kind: str) -> bool:
    """Whether this task capability needs write-ahead effect recovery.

    The manifest is the policy source; this adapter never maintains a second
    capability catalog.  A receipt remains optional only where the existing
    worker has no verified receipt contract, in which case recovery stays
    fail-closed as ``unknown``.
    """
    from modules import capability_manifest
    try:
        row = capability_manifest.from_task_tool(kind)
    except ValueError:
        row = capability_manifest.from_goal_tool(kind)
    return row['replay'] == 'conditional' and row['reconciliation'] == 'required'


def _checked(expected: dict) -> dict:
    """Validate legacy and plan-fenced effects without downgrading schemas.

    Canonical Scheduler effects bind their intent/receipt to the immutable
    plan version and node digest. Legacy effects retain their original v1
    shape; the two identities cannot be confused or silently truncated.
    """
    from modules import worker_result
    if not isinstance(expected, dict):
        raise ValueError('Effect recovery WorkerResult fence geçersiz.')
    fields = set(expected)
    if fields == set(_FENCE):
        schema = worker_result.SCHEMA
    elif fields == set(_FENCE).union(worker_result.PLAN_FENCE):
        schema = worker_result.PLAN_SCHEMA
    else:
        raise ValueError('Effect recovery WorkerResult fence geçersiz.')
    probe = {'schema':schema, 'status':'succeeded', 'evidence':[], **expected}
    worker_result.validate(probe)
    return copy.deepcopy(expected)


def _effect_id(expected: dict) -> str:
    payload = json.dumps(_checked(expected), ensure_ascii=False, sort_keys=True, separators=(',', ':'))
    return 'effect:' + hashlib.sha256(payload.encode('utf-8')).hexdigest()


def _journal(expected: dict, *, existing=False):
    expected = _checked(expected)
    from modules import goal_executor
    path = goal_executor._root(expected['owner']) / (expected['job_id'] + '.effects.json')
    journal=effect_journal.PersistentJournal(path)
    effect_id=_effect_id(expected)
    if (existing and 'plan_version' not in expected
            and journal.status(effect_id)=='not_started'):
        # A planned effect NEVER adopts a journal receipt via a partial
        # legacy-field match: its plan version, input and node digest are one
        # indivisible command fence. Legacy v1 recovery retains its prior
        # lifecycle-version compatibility.
        # Lifecycle CAS may advance across restart. The immutable operation
        # identity/attempt/input must still match exactly; never adopt a result
        # from a renamed task, new input, new attempt or ambiguous old entries.
        fields=('owner','job_id','command_id','capability_id','capability_version','input_digest')
        matches=[row for row in journal.intents() if all(row[k]==expected[k] for k in fields)]
        if len(matches)>1:raise effect_journal.ContractViolation('Effect recovery kaydı tekil değil.')
        if matches:effect_id=matches[0]['effect_id']
    return journal, effect_id


def record_intent(expected: dict) -> str:
    """Persist one immutable intent before a provider effect can begin."""
    expected = _checked(expected)
    from modules import goal_executor, goal_job_control
    import re
    root = goal_executor._root(expected['owner'])
    with goal_job_control.locked(root, expected['job_id']):
        journal, effect_id = _journal(expected)
        for prior in journal.intents():
            if (prior['owner'] == expected['owner'] and prior['job_id'] == expected['job_id']
                    and (prior['command_id'] == expected['command_id']
                         or re.fullmatch(re.escape(expected['step_id']) + r':\d+(?::p\d+)?', prior['command_id']))):
                raise EffectReplayBlocked(
                    'Bu effect adımı daha önce başladı; yeni attempt/sürüm replay yetkisi değildir. Salt-okunur recovery gerekli.')
        journal.record_intent({
            'schema':'effect_intent.v1', 'effect_id':effect_id,
            'owner':expected['owner'], 'job_id':expected['job_id'],
            'command_id':expected['command_id'], 'capability_id':expected['capability_id'],
            'capability_version':expected['capability_version'], 'input_digest':expected['input_digest'],
        })
    return effect_id


def status(expected: dict) -> str:
    journal, effect_id = _journal(expected,existing=True)
    return journal.status(effect_id)


def _receipt_ref(output: dict) -> str:
    receipt = output.get('receipt') if isinstance(output, dict) else None
    if not isinstance(receipt, dict):
        raise ValueError('Reconcile sonucu doğrulanmış provider receipt taşımıyor.')
    service = receipt.get('service'); remote_id = receipt.get('remote_id')
    if not isinstance(service, str) or not service or not isinstance(remote_id, str) or not remote_id:
        raise ValueError('Reconcile provider receipt kimliği geçersiz.')
    return service + ':' + remote_id


def record_receipt(expected: dict, output: dict) -> None:
    """Persist a verified provider receipt after a normal or reconciled result."""
    from modules import goal_executor, goal_job_control
    with goal_job_control.locked(goal_executor._root(expected['owner']), expected['job_id']):
        journal, effect_id = _journal(expected,existing=True)
        if journal.status(effect_id) == 'not_started':
            raise effect_journal.ContractViolation('Effect intent yokken receipt kabul edilmez.')
        if journal.status(effect_id) == 'unknown':
            journal.record_receipt({
                'schema':'effect_receipt.v1', 'effect_id':effect_id,
                'provider_receipt_ref':_receipt_ref(output), 'verified':True,
            })


def reconcile(expected: dict, read_only_reconcile, *, receipt_readback=False):
    """Read-only recovery: no intent means no reconcile; no effect is retried."""
    expected = _checked(expected)
    journal, effect_id = _journal(expected,existing=True)
    decision = crash_recovery.decide(journal, effect_id)
    if decision['state'] == 'not_started':
        return None
    if decision['state'] == 'succeeded':
        # Only the existing publish Outbox has local exact-payload receipt
        # readback. Other capabilities retain the no-provider-reread contract.
        if not receipt_readback or expected['capability_id']!='task.publish':return None
        current=runtime_worker_result.canonical_snapshot(expected)
        fields=tuple(k for k in _FENCE if k!='expected_job_version')
        if any(row.get('kind')=='worker_result' and all(row.get(k)==expected[k] for k in fields)
               for row in current['evidence']):
            return None
    output = read_only_reconcile()
    if not isinstance(output, dict) or output.get('state') != 'done':
        return output
    # A provider receipt must not be recorded as verified on a worker claim
    # alone. Domain verification comes before receipt and WorkerResult CAS.
    from modules import goal_tools
    goal_tools.verify(output, expected['owner'])
    if decision['state']=='succeeded' and journal.receipt(effect_id)['provider_receipt_ref']!=_receipt_ref(output):
        raise effect_journal.ContractViolation('Kalıcı receipt ile yerel readback eşleşmiyor.')
    if decision['state'] == 'unknown':
        record_receipt(expected, output)
    fenced = worker_result_hook.wrap_output(output, expected)
    return runtime_worker_result.accept_and_commit(fenced, expected)
