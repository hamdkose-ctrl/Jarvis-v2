"""Kullanıcıya özel, maskeli izin kararları; hiçbir karar yoluna bağlı değildir."""
import json
import os
import re
import tempfile
import threading
import time
from pathlib import Path

from config import DATA_DIR
from modules.misroute_log import _clean
from modules.diagnostics import record_failure as _record_failure

_lock = threading.RLock()
_LIMIT = 500
_MAX_BYTES = 2_000_000
_DECISIONS = frozenset({'allow', 'ask', 'deny'})
_VIA = frozenset({'outbox', 'desktop', 'browser', 'file', 'system'})
_SLUG = re.compile(r'[a-z0-9][a-z0-9_-]{0,99}')
_DEVICES = {'con', 'prn', 'aux', 'nul'} | {f'{p}{i}' for p in ('com', 'lpt') for i in range(1, 10)}


def _path(owner):
    if not isinstance(owner, str) or not _SLUG.fullmatch(owner) or owner in _DEVICES:
        raise ValueError('Geçerli, küçük harfli bir kullanıcı slug değeri gerekli.')
    root = DATA_DIR / 'permission_audit'
    path = root / f'{owner}.json'
    for item in (root, path):
        if item.is_symlink() or (hasattr(item, 'is_junction') and item.is_junction()):
            raise ValueError('Denetim yolu sembolik bağ veya junction olamaz.')
    return path


def _choice(value, allowed):
    if not isinstance(value, str) or value not in allowed:
        raise ValueError('Geçersiz izin kararı veya yöntem.')


def _read(path):
    try:
        with path.open('rb') as handle:
            raw = handle.read(_MAX_BYTES + 1)
        if len(raw) > _MAX_BYTES:
            raise ValueError('Denetim günlüğü boyut sınırını aştı.')
        rows = json.loads(raw.decode('utf-8'))
        if not isinstance(rows, list) or len(rows) > _LIMIT:
            raise ValueError('Geçersiz denetim günlüğü yapısı.')
        for row in rows:
            if (not isinstance(row, dict)
                    or set(row) != {'t', 'decision', 'class', 'target', 'via', 'reason'}
                    or type(row['t']) not in (int, float) or not 0 <= row['t'] <= 1e12
                    or not all(isinstance(row[k], str) for k in ('class', 'target', 'reason'))
                    or not row['class'].strip() or len(row['class']) > 80
                    or len(row['target']) > 200 or len(row['reason']) > 200):
                raise ValueError('Geçersiz denetim kaydı.')
            _choice(row['decision'], _DECISIONS)
            _choice(row['via'], _VIA)
        return rows
    except FileNotFoundError:
        return []
    except (UnicodeError, ValueError):
        _record_failure('modules/permission_audit.py:read')
        # Önceki bozuk yedekler ezilmez. Taşıma başarısızsa asıl dosya da ezilmez.
        backup = path.with_name(path.name + '.bozuk')
        i = 0
        while backup.exists() or backup.is_symlink():
            i += 1
            backup = path.with_name(f'{path.name}.{i}.bozuk')
        os.replace(path, backup)
        return []


def _save(path, rows):
    temporary = None
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary = tempfile.mkstemp(prefix='.permission-', suffix='.tmp', dir=path.parent)
        with os.fdopen(fd, 'w', encoding='utf-8') as handle:
            json.dump(rows[-_LIMIT:], handle, ensure_ascii=False, allow_nan=False)
            handle.flush()
            os.fsync(handle.fileno())
        for attempt in range(4):
            try:
                os.replace(temporary, path)
                break
            except PermissionError:
                if attempt == 3:
                    raise
                time.sleep(0.02 * (attempt + 1))
    finally:
        if temporary is not None:
            try:
                Path(temporary).unlink(missing_ok=True)
            except OSError:
                _record_failure('modules/permission_audit.py:temporary_cleanup')


def record(owner, decision: str, action_class: str, target: str, via: str, reason: str = '') -> None:
    """Kararı yerelde tutar; geçersiz girdi ValueError, kayıt hatası yalnız tanı üretir."""
    _choice(decision, _DECISIONS)
    _choice(via, _VIA)
    if not all(isinstance(value, str) for value in (action_class, target, reason)) or not action_class.strip():
        raise ValueError('Sınıf, hedef ve gerekçe metin olmalı; sınıf boş olamaz.')
    with _lock:
        path = _path(owner)
        try:
            row = {'t': time.time(), 'decision': decision, 'class': _clean(action_class, 80),
                   'target': _clean(target, 200), 'via': via, 'reason': _clean(reason, 200)}
            rows = _read(path)
            rows.append(row)
            _save(path, rows)
        except Exception:
            _record_failure('modules/permission_audit.py:record')


def recent(owner, limit=50) -> list[dict]:
    """En yeni kayıt önce gelir; eksik günlük dosya oluşturmaz."""
    if type(limit) is not int or limit < 0:
        raise ValueError('Kayıt sınırı sıfır veya pozitif bir tam sayı olmalı.')
    with _lock:
        path = _path(owner)
        if limit == 0:
            return []
        try:
            return list(reversed(_read(path)[-min(limit, _LIMIT):]))
        except Exception:
            _record_failure('modules/permission_audit.py:recent')
            return []


def clear(owner) -> int:
    """Kullanıcının günlüğünü kaldırır, silinen kayıt sayısını verir; bozuk yedekler kalır."""
    with _lock:
        path = _path(owner)
        try:
            count = len(_read(path))
            path.unlink(missing_ok=True)
            return count
        except Exception:
            _record_failure('modules/permission_audit.py:clear')
            return 0
