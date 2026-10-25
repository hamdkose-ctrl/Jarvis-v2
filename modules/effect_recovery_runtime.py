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
    if not isinstance(expected, dict) or set(expected) != set(_FENCE):
        raise ValueError('Effect recovery WorkerResult fence geçersiz.')
    probe = {'schema':'worker_result.v1', 'status':'succeeded', 'evidence':[], **expected}
    from modules import worker_result
    worker_result.validate(probe)
    return copy.deepcopy(expected)


def _effect_id(expected: dict) -> str:
    payload = json.dumps(_checked(expected), ensure_ascii=False, sort_keys=True, separators=(',', ':'))
    return 'effect:' + hashlib.sha256(payload.encode('utf-8')).hexdigest()


def _journal(expected: dict):
    expected = _checked(expected)
    from modules import goal_executor
    path = goal_executor._root(expected['owner']) / (expected['job_id'] + '.effects.json')
    return effect_journal.PersistentJournal(path), _effect_id(expected)


def record_intent(expected: dict) -> str:
    """Persist one immutable intent before a provider effect can begin."""
    expected = _checked(expected)
    journal, effect_id = _journal(expected)
    if journal.status(effect_id) != 'not_started':
        return effect_id
    journal.record_intent({
        'schema':'effect_intent.v1', 'effect_id':effect_id,
        'owner':expected['owner'], 'job_id':expected['job_id'],
        'command_id':expected['command_id'], 'capability_id':expected['capability_id'],
        'capability_version':expected['capability_version'], 'input_digest':expected['input_digest'],
    })
    return effect_id


def status(expected: dict) -> str:
    journal, effect_id = _journal(expected)
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
    journal, effect_id = _journal(expected)
    if journal.status(effect_id) == 'not_started':
        raise effect_journal.ContractViolation('Effect intent yokken receipt kabul edilmez.')
    if journal.status(effect_id) == 'unknown':
        journal.record_receipt({
            'schema':'effect_receipt.v1', 'effect_id':effect_id,
            'provider_receipt_ref':_receipt_ref(output), 'verified':True,
        })


def reconcile(expected: dict, read_only_reconcile):
    """Read-only recovery: no intent means no reconcile; no effect is retried."""
    expected = _checked(expected)
    journal, effect_id = _journal(expected)
    decision = crash_recovery.decide(journal, effect_id)
    if decision['state'] == 'not_started':
        return None
    if decision['state'] == 'succeeded':
        # A verified receipt proves the effect happened.  It is not itself a
        # global completion decision and must not trigger a provider reread.
        return None
    output = read_only_reconcile()
    if not isinstance(output, dict) or output.get('state') != 'done':
        return output
    if decision['state'] == 'unknown':
        record_receipt(expected, output)
    fenced = worker_result_hook.wrap_output(output, expected)
    return runtime_worker_result.accept_and_commit(fenced, expected)
