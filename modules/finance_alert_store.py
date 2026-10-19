"""User-local alarm rules and states; no watchlist dependency, polling, network or model calls."""
import copy
import json
import math
import os
from pathlib import Path
import re
import secrets
import tempfile
import threading
import time

from config import DATA_DIR
from modules import finance_alerts
from modules.diagnostics import record_failure as _record_failure

_ROOT = DATA_DIR / 'finance_alerts'
_lock = threading.RLock()
_LIMIT = 21
_MAX_BYTES = 1_000_000
_SLUG = re.compile(r'[a-z0-9][a-z0-9_-]{0,99}')
_ID = re.compile(r'[a-z0-9]{8,24}')
_DEVICES = {'con', 'prn', 'aux', 'nul'} | {f'{prefix}{i}' for prefix in ('com', 'lpt') for i in range(1, 10)}
_RULE_FIELDS = {'kind', 'symbol', 'op', 'value', 'cooldown_s'}


def _guard(path):
    for item in (path, _ROOT, *_ROOT.parents):
        if item.is_symlink() or (hasattr(item, 'is_junction') and item.is_junction()):
            raise ValueError('Alarm deposu yolu sembolik bağ veya junction olamaz.')


def _path(owner):
    if not isinstance(owner, str) or not _SLUG.fullmatch(owner) or owner in _DEVICES:
        raise ValueError('Geçerli, küçük harfli bir kullanıcı slug değeri gerekli.')
    path = _ROOT / (owner + '.json')
    _guard(path)
    return path


def _normalise_rule(rule):
    try:
        symbol, op, value, cooldown = finance_alerts._validate_rule(rule)
    except (TypeError, OverflowError):
        raise ValueError('Geçersiz alarm kuralı.') from None
    if set(rule) - _RULE_FIELDS:
        raise ValueError('Alarm kuralında bilinmeyen alan var.')
    return {'kind': rule['kind'], 'symbol': symbol, 'op': op, 'value': value, 'cooldown_s': cooldown}


def _number(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError('Geçersiz alarm durum değeri.')
    try:
        if not math.isfinite(value) or value < 0:
            raise ValueError('Geçersiz alarm durum değeri.')
        return float(value)
    except OverflowError:
        raise ValueError('Geçersiz alarm durum değeri.') from None


def _normalise_state(state):
    if not isinstance(state, dict) or set(state) != {'price', 'fired_at'}:
        raise ValueError('Geçersiz alarm durumu.')
    return {key: None if value is None else _number(value) for key, value in state.items()}


def _identity(rule):
    return tuple(rule[key] for key in ('kind', 'symbol', 'op', 'value'))


def _empty():
    return {'version': 1, 'rules': [], 'states': {}}


def _validate_document(data):
    if (not isinstance(data, dict) or set(data) != {'version', 'rules', 'states'} or
            type(data['version']) is not int or data['version'] != 1 or
            not isinstance(data['rules'], list) or len(data['rules']) > _LIMIT or
            not isinstance(data['states'], dict)):
        raise ValueError('Geçersiz alarm deposu yapısı.')
    ids, identities = set(), set()
    for row in data['rules']:
        if not isinstance(row, dict) or set(row) != _RULE_FIELDS | {'id', 'created'}:
            raise ValueError('Geçersiz alarm deposu kaydı.')
        ident = row['id']
        if not isinstance(ident, str) or not _ID.fullmatch(ident) or ident in ids:
            raise ValueError('Geçersiz alarm kimliği.')
        _number(row['created'])
        normalised = _normalise_rule({key: row[key] for key in _RULE_FIELDS})
        if any(row[key] != value for key, value in normalised.items()):
            raise ValueError('Normalleştirilmemiş alarm kuralı.')
        signature = _identity(row)
        if signature in identities:
            raise ValueError('Tekrarlanan alarm kuralı.')
        ids.add(ident); identities.add(signature)
    for ident, state in data['states'].items():
        if ident not in ids:
            raise ValueError('Bilinmeyen alarm durum kaydı.')
        _normalise_state(state)
    return data


def _backup_path(path):
    for index in range(1000):
        candidate = path.with_suffix('.bozuk') if index == 0 else path.with_name(f'{path.stem}.{index}.bozuk')
        if not os.path.lexists(candidate):
            return candidate
    raise OSError('Bozuk alarm deposu için yedek adı üretilemedi.')


def _read(path):
    _guard(path)
    try:
        with path.open('rb') as handle:
            raw = handle.read(_MAX_BYTES + 1)
        if len(raw) > _MAX_BYTES:
            raise ValueError('Alarm deposu boyut sınırı aşıldı.')
        return _validate_document(json.loads(raw.decode('utf-8')))
    except FileNotFoundError:
        return _empty()
    except (UnicodeError, ValueError, TypeError, OverflowError, RecursionError):
        _record_failure('modules/finance_alert_store.py:read')
        try:
            _guard(path)
            path.replace(_backup_path(path))
        except OSError:
            _record_failure('modules/finance_alert_store.py:backup')
            raise OSError('Bozuk alarm deposu yedeklenemedi.') from None
        return _empty()
    except OSError:
        _record_failure('modules/finance_alert_store.py:read_io')
        raise OSError('Alarm deposu okunamadı.') from None


def _save(path, document):
    raw = json.dumps(document, ensure_ascii=False, allow_nan=False).encode('utf-8')
    if len(raw) > _MAX_BYTES:
        raise ValueError('Alarm deposu boyut sınırı aşıldı.')
    temporary = None
    try:
        _guard(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary = tempfile.mkstemp(prefix='.finance-alerts-', suffix='.tmp', dir=path.parent)
        with os.fdopen(fd, 'wb') as handle:
            handle.write(raw)
            handle.flush()
            os.fsync(handle.fileno())
        for attempt in range(4):
            try:
                _guard(path)
                os.replace(temporary, path)
                temporary = None
                break
            except PermissionError:
                if attempt == 3:
                    raise
                time.sleep(0.02 * (attempt + 1))
    except OSError:
        _record_failure('modules/finance_alert_store.py:write')
        raise OSError('Alarm deposu yazılamadı.') from None
    finally:
        if temporary is not None:
            try:
                Path(temporary).unlink(missing_ok=True)
            except OSError:
                _record_failure('modules/finance_alert_store.py:temporary_cleanup')


def add_rule(owner, rule: dict) -> dict:
    normalised = _normalise_rule(rule)
    with _lock:
        path = _path(owner)
        document = _read(path)
        for row in document['rules']:
            if _identity(row) == _identity(normalised):
                return copy.deepcopy(row)
        if len(document['rules']) >= _LIMIT:
            raise ValueError('Alarm listesi dolu (en fazla 20).')
        ids = {row['id'] for row in document['rules']}
        for _ in range(16):
            ident = secrets.token_hex(6)
            if ident not in ids:
                break
        else:
            raise OSError('Benzersiz alarm kimliği üretilemedi.')
        row = {**normalised, 'id': ident, 'created': _number(time.time())}
        document['rules'].append(row)
        _save(path, document)
        return copy.deepcopy(row)


def list_rules(owner) -> list[dict]:
    with _lock:
        return copy.deepcopy(_read(_path(owner))['rules'])


def remove_rule(owner, rule_id) -> bool:
    with _lock:
        path = _path(owner)
        document = _read(path)
        kept = [row for row in document['rules'] if row['id'] != rule_id]
        if len(kept) == len(document['rules']):
            return False
        document['rules'] = kept
        document['states'].pop(rule_id, None)
        _save(path, document)
        return True


def clear(owner) -> int:
    with _lock:
        path = _path(owner)
        document = _read(path)
        if path.exists():
            try:
                _guard(path)
                path.unlink()
            except OSError:
                _record_failure('modules/finance_alert_store.py:clear')
                raise OSError('Alarm deposu temizlenemedi.') from None
        return len(document['rules'])


def get_state(owner, rule_id) -> dict | None:
    with _lock:
        document = _read(_path(owner))
        if not any(row['id'] == rule_id for row in document['rules']):
            raise ValueError('Bilinmeyen alarm kuralı.')
        return copy.deepcopy(document['states'].get(rule_id))


def set_state(owner, rule_id, state: dict) -> None:
    normalised = _normalise_state(state)
    with _lock:
        path = _path(owner)
        document = _read(path)
        if not any(row['id'] == rule_id for row in document['rules']):
            raise ValueError('Bilinmeyen alarm kuralı.')
        document['states'][rule_id] = normalised
        _save(path, document)
