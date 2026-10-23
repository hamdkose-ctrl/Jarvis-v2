"""Pure three-branch crash-recovery decision contract.

It never retries or reconciles an effect.  The caller must route any proposed
new side effect through the normal invariant/authority/permission/effect line.
"""
from __future__ import annotations


def decide(journal, effect_id: str) -> dict:
    """Classify one journaled effect without causing an external action."""
    if not isinstance(effect_id, str) or not effect_id:
        raise ValueError('Effect kimliği geçersiz.')
    status = journal.status(effect_id)
    if status == 'not_started':
        return {
            'state': 'not_started', 'action': 'policy_required',
            'reason_code': 'EFFECT_INTENT_MISSING',
        }
    if status == 'unknown':
        return {
            'state': 'unknown', 'action': 'read_only_reconcile',
            'reason_code': 'RECEIPT_MISSING_NO_BLIND_RETRY',
        }
    if status == 'succeeded':
        return {
            'state': 'succeeded', 'action': 'no_retry',
            'reason_code': 'VERIFIED_RECEIPT_PRESENT',
        }
    raise ValueError('Effect journal durumu bilinmiyor.')
