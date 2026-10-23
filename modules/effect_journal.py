"""Append-only effect intent/receipt contract.

The journal deliberately does not execute, retry or reconcile effects.  It is
the durable boundary contract consumed by the later crash-recovery slice.
"""
from __future__ import annotations

import copy
import json


class ContractViolation(ValueError):
    pass


_INTENT = frozenset({'schema', 'effect_id', 'owner', 'job_id', 'command_id',
                     'capability_id', 'capability_version', 'input_digest'})
_RECEIPT = frozenset({'schema', 'effect_id', 'provider_receipt_ref', 'verified'})


def _json(row):
    try:
        json.dumps(row, ensure_ascii=False, allow_nan=False)
    except (TypeError, ValueError):
        raise ValueError('Effect journal JSON uyumlu olmalı.') from None


def _text(row, keys):
    if not all(isinstance(row.get(key), str) and row[key] for key in keys):
        raise ValueError('Effect journal kimliği geçersiz.')


def validate_intent(intent: dict) -> dict:
    if not isinstance(intent, dict) or set(intent) != _INTENT or intent.get('schema') != 'effect_intent.v1':
        raise ValueError('Effect intent şeması geçersiz.')
    _text(intent, _INTENT - {'schema'})
    if len(intent['input_digest']) != 64 or any(char not in '0123456789abcdef' for char in intent['input_digest']):
        raise ValueError('Effect intent digest geçersiz.')
    _json(intent); return copy.deepcopy(intent)


def validate_receipt(receipt: dict) -> dict:
    if not isinstance(receipt, dict) or set(receipt) != _RECEIPT or receipt.get('schema') != 'effect_receipt.v1':
        raise ValueError('Effect receipt şeması geçersiz.')
    _text(receipt, {'effect_id', 'provider_receipt_ref'})
    if receipt.get('verified') is not True: raise ValueError('Effect receipt doğrulanmış olmalı.')
    _json(receipt); return copy.deepcopy(receipt)


class Journal:
    """In-memory append-only model; persistence adapter remains outside 4c."""
    def __init__(self): self._entries = {}

    def record_intent(self, intent: dict) -> dict:
        row = validate_intent(intent)
        if row['effect_id'] in self._entries: raise ValueError('Effect intent zaten var.')
        self._entries[row['effect_id']] = {'intent': row, 'receipt': None}
        return copy.deepcopy(row)

    def record_receipt(self, receipt: dict) -> dict:
        row = validate_receipt(receipt)
        entry = self._entries.get(row['effect_id'])
        if entry is None: raise ContractViolation('Intent kaydından önce dış etki bildirildi.')
        if entry['receipt'] is not None: raise ValueError('Effect receipt zaten var.')
        entry['receipt'] = row
        return copy.deepcopy(row)

    def status(self, effect_id: str) -> str:
        entry = self._entries.get(effect_id)
        if entry is None: return 'not_started'
        return 'succeeded' if entry['receipt'] else 'unknown'
