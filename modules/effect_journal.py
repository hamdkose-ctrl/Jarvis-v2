"""Append-only effect intent/receipt contract with an optional durable store.

The journal never executes, retries or reconciles effects. PersistentJournal is
the restart-safe adapter consumed by crash recovery; writes are committed
atomically before the in-memory snapshot advances.
"""
from __future__ import annotations

import copy
import json
from pathlib import Path

import release_guard


class ContractViolation(ValueError):
    pass


_INTENT = frozenset({'schema', 'effect_id', 'owner', 'job_id', 'command_id',
                     'capability_id', 'capability_version', 'input_digest'})
_RECEIPT = frozenset({'schema', 'effect_id', 'provider_receipt_ref', 'verified'})
_STORE_SCHEMA = 'effect_journal_store.v1'


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


def _validated_entries(entries) -> dict:
    if not isinstance(entries, dict):
        raise ValueError('Effect journal kalıcı kayıt biçimi geçersiz.')
    accepted = {}
    for effect_id, entry in entries.items():
        if not isinstance(effect_id, str) or not effect_id or not isinstance(entry, dict) or set(entry) != {'intent', 'receipt'}:
            raise ValueError('Effect journal kalıcı kayıt biçimi geçersiz.')
        intent = validate_intent(entry['intent'])
        if intent['effect_id'] != effect_id:
            raise ValueError('Effect journal intent kimliği kayıt anahtarıyla eşleşmiyor.')
        receipt = entry['receipt']
        if receipt is not None:
            receipt = validate_receipt(receipt)
            if receipt['effect_id'] != effect_id:
                raise ValueError('Effect journal receipt kimliği kayıt anahtarıyla eşleşmiyor.')
        accepted[effect_id] = {'intent': intent, 'receipt': receipt}
    return accepted


def _load(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding='utf-8'))
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise ValueError('Effect journal kalıcı kaydı bozuk.') from None
    if not isinstance(payload, dict) or set(payload) != {'schema', 'entries'} or payload.get('schema') != _STORE_SCHEMA:
        raise ValueError('Effect journal kalıcı kayıt şeması geçersiz.')
    return _validated_entries(payload['entries'])


def _persist(path: Path, entries: dict) -> None:
    accepted = _validated_entries(entries)
    payload = {'schema': _STORE_SCHEMA, 'entries': accepted}
    _json(payload)
    path.parent.mkdir(parents=True, exist_ok=True)
    release_guard.atomic(path, json.dumps(payload, ensure_ascii=False, sort_keys=True).encode('utf-8'))


class Journal:
    """In-memory append-only model."""
    def __init__(self): self._entries = {}

    def intents(self):
        """Immutable readback for admission/recovery; never exposes writers."""
        return tuple(copy.deepcopy(entry['intent']) for entry in self._entries.values())

    def receipt(self, effect_id):
        return copy.deepcopy(self._entries.get(effect_id, {}).get('receipt'))

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


class PersistentJournal(Journal):
    """Restart-safe append-only journal stored as one atomic JSON snapshot."""
    def __init__(self, path):
        self.path = Path(path)
        self._entries = _load(self.path)

    def record_intent(self, intent: dict) -> dict:
        row = validate_intent(intent)
        if row['effect_id'] in self._entries:
            raise ValueError('Effect intent zaten var.')
        next_entries = copy.deepcopy(self._entries)
        next_entries[row['effect_id']] = {'intent': row, 'receipt': None}
        _persist(self.path, next_entries)
        self._entries = next_entries
        return copy.deepcopy(row)

    def record_receipt(self, receipt: dict) -> dict:
        row = validate_receipt(receipt)
        entry = self._entries.get(row['effect_id'])
        if entry is None:
            raise ContractViolation('Intent kaydından önce dış etki bildirildi.')
        if entry['receipt'] is not None:
            raise ValueError('Effect receipt zaten var.')
        next_entries = copy.deepcopy(self._entries)
        next_entries[row['effect_id']]['receipt'] = row
        _persist(self.path, next_entries)
        self._entries = next_entries
        return copy.deepcopy(row)
