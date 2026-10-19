"""Kullanıcıya özel süreli mesaj izinleri; yürütme yollarına bağlı değildir.

Biçim permission_gate ile aynıdır: message_out={hedef: son_zaman}, apps_never=[...].
JARVIS_HOME verilirse onu, yoksa mevcut config.DATA_DIR alanını kullanır.
Sahiplik mevcut service_store.identity kapısında denetlenir. Kilit süreç içidir.
"""
import copy
import json
import math
import os
from pathlib import Path
import re
import tempfile
import threading
import time

from config import DATA_DIR
from modules import service_store

ROOT = Path(os.environ.get('JARVIS_HOME') or DATA_DIR) / 'permission_grants'
_LOCK = threading.RLock()
_LIMIT = 50
_MAX_SECONDS = 24 * 60 * 60
_MAX_BYTES = 64000
_DEVICES = {'con', 'prn', 'aux', 'nul'} | {f'{p}{n}' for p in ('com', 'lpt') for n in range(1, 10)}


def _empty():
    return {'message_out': {}, 'apps_never': []}


def _guard(path):
    for item in (path, ROOT, *ROOT.parents):
        if item.is_symlink() or (hasattr(item, 'is_junction') and item.is_junction()):
            raise ValueError('İzin kaydı yolu sembolik bağ veya junction olamaz.')


def _path(user):
    service_store.identity(user)
    if (not isinstance(user, str) or not re.fullmatch(r'[a-z0-9][a-z0-9_-]{0,99}', user)
            or user in _DEVICES):
        raise ValueError('Geçersiz kullanıcı slug değeri.')
    path = ROOT / (user + '.json')
    _guard(path)
    return path


def _number(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError('Geçersiz izin zamanı veya süresi.')
    try:
        number = float(value)
    except (OverflowError, ValueError):
        raise ValueError('Geçersiz izin zamanı veya süresi.') from None
    if not math.isfinite(number) or number < 0:
        raise ValueError('Geçersiz izin zamanı veya süresi.')
    return number


def _now(now):
    return _number(time.time() if now is None else now)


def _target(target):
    if (not isinstance(target, str) or not target.strip() or len(target) > 320
            or '*' in target or any(ord(char) < 32 or ord(char) == 127 for char in target)):
        raise ValueError('Kesin bir mesaj hedefi gerekli.')
    target = target.strip()
    return target.casefold() if '@' in target else target


def _read(path):
    try:
        with path.open('rb') as handle:
            raw = handle.read(_MAX_BYTES + 1)
        if len(raw) > _MAX_BYTES:
            return _empty()
        data = json.loads(raw.decode('utf-8'))
        if (not isinstance(data, dict) or set(data) != {'message_out', 'apps_never'}
                or not isinstance(data['message_out'], dict) or len(data['message_out']) > _LIMIT
                or not isinstance(data['apps_never'], list) or len(data['apps_never']) > 50
                or any(not isinstance(app, str) or len(app) > 320 for app in data['apps_never'])):
            return _empty()
        messages = {}
        for target, expiry in data['message_out'].items():
            target = _target(target)
            expiry = _number(expiry)
            # Differently cased duplicate email keys must not extend an earlier expiry.
            messages[target] = min(expiry, messages.get(target, expiry))
        return {'message_out': messages, 'apps_never': data['apps_never']}
    except (OSError, UnicodeError, ValueError, TypeError, RecursionError, OverflowError):
        return _empty()


def _write(path, data):
    raw = json.dumps(data, ensure_ascii=False, allow_nan=False).encode('utf-8')
    if len(raw) > _MAX_BYTES:
        raise ValueError('İzin kaydı boyut sınırı aşıldı.')
    _guard(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix='.permission-grants-', suffix='.tmp', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as handle:
            handle.write(raw)
            handle.flush()
            os.fsync(handle.fileno())
        _guard(path)
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def _prune(data, now):
    old = len(data['message_out'])
    data['message_out'] = {target: expiry for target, expiry in data['message_out'].items() if expiry > now}
    return old - len(data['message_out'])


def load(user):
    """Yalnız geçerli izinleri döndürür; eksik/bozuk dosya boş, temizlik hatası fail-closed."""
    with _LOCK:
        path = _path(user)
        data = _read(path)
        if _prune(data, _now(None)):
            try:
                _write(path, data)
            except OSError:
                pass  # Diskte temizlenemese bile dolmuş izin asla sonuçta bulunmaz.
        return copy.deepcopy(data)


def grant_message(user, target, seconds, now=None):
    """En fazla 24 saatlik kesin hedef iznini atomik saklar; dolu depoda yenileme mümkündür."""
    target, seconds, moment = _target(target), _number(seconds), _now(now)
    if not 0 < seconds <= _MAX_SECONDS:
        raise ValueError('İzin süresi 0 ile 24 saat arasında olmalı.')
    expiry = _number(moment + seconds)
    with _LOCK:
        path = _path(user)
        data = _read(path)
        _prune(data, moment)
        if target not in data['message_out'] and len(data['message_out']) >= _LIMIT:
            raise ValueError('İzin listesi dolu (en fazla 50).')
        data['message_out'][target] = expiry
        _write(path, data)
        return copy.deepcopy(data)


def revoke(user, target):
    """Bir kesin hedefin iznini kaldırır; kaldırılmışsa True döndürür."""
    target = _target(target)
    with _LOCK:
        path = _path(user)
        data = _read(path)
        if target not in data['message_out']:
            return False
        del data['message_out'][target]
        _prune(data, _now(None))
        _write(path, data)
        return True


def purge(user, now=None):
    """Süresi dolan mesaj kayıtlarını siler ve silinen sayıyı döndürür."""
    moment = _now(now)
    with _LOCK:
        path = _path(user)
        data = _read(path)
        removed = _prune(data, moment)
        if removed:
            _write(path, data)
        return removed
