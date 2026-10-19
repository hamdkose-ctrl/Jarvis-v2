"""Kullanıcıya özel yerel finans takip listesi depolaması; ağ ve model çağrısı yok."""
import json
import os
import re
import tempfile
import threading
import time
from pathlib import Path

from config import DATA_DIR
from modules import turkish_text
from modules.diagnostics import record_failure as _record_failure

_ROOT = DATA_DIR / 'finance_watchlists'
_lock = threading.RLock()
_LIMIT = 20
_MAX_BYTES = 1_000_000
_KINDS = {'doviz', 'kripto', 'altin', 'hisse'}
_SLUG = re.compile(r'[a-z0-9][a-z0-9_-]{0,99}')
_SYMBOL = re.compile(r'[A-Z0-9]{1,12}')
_DEVICES = {'con', 'prn', 'aux', 'nul'} | {f'{p}{i}' for p in ('com', 'lpt') for i in range(1, 10)}


def _path(owner):
    if not isinstance(owner, str) or not _SLUG.fullmatch(owner) or owner in _DEVICES:
        raise ValueError('Geçerli, küçük harfli bir kullanıcı slug değeri gerekli.')
    path = _ROOT / f'{owner}.json'
    for item in (_ROOT, path):
        if item.is_symlink() or (hasattr(item, 'is_junction') and item.is_junction()):
            raise ValueError('Takip listesi yolu sembolik bağ veya junction olamaz.')
    return path


def _normalise(kind, symbol):
    if not isinstance(kind, str) or kind not in _KINDS:
        raise ValueError('Geçersiz takip türü.')
    if not isinstance(symbol, str):
        raise ValueError('Geçersiz sembol.')
    value = turkish_text.fold(symbol).upper()
    if not _SYMBOL.fullmatch(value):
        raise ValueError('Sembol 1-12 karakter ve yalnız harf/rakam olmalı.')
    if kind == 'altin' and value != 'GRAM':
        raise ValueError("Altın için yalnız 'GRAM' sembolü geçerli.")
    return value


def _backup_path(path):
    candidate = path.with_suffix('.bozuk')
    if not candidate.exists():
        return candidate
    for index in range(1, 1000):
        candidate = path.with_name(f'{path.stem}.{index}.bozuk')
        if not candidate.exists():
            return candidate
    raise OSError('Bozuk takip listesi için yedek adı üretilemedi.')


def _read(path):
    try:
        with path.open('rb') as handle:
            raw = handle.read(_MAX_BYTES + 1)
        if len(raw) > _MAX_BYTES:
            raise ValueError('Takip listesi boyut sınırı aşıldı.')
        rows = json.loads(raw.decode('utf-8'))
        if not isinstance(rows, list) or len(rows) > _LIMIT:
            raise ValueError('Geçersiz takip listesi yapısı.')
        for row in rows:
            if not isinstance(row, dict) or set(row) != {'kind', 'symbol'}:
                raise ValueError('Geçersiz takip listesi kaydı.')
            symbol = _normalise(row.get('kind'), row.get('symbol'))
            if symbol != row['symbol']:
                raise ValueError('Normalleştirilmemiş takip listesi kaydı.')
        return rows
    except FileNotFoundError:
        return []
    except (UnicodeError, json.JSONDecodeError, ValueError):
        _record_failure('modules/finance_watchlist.py:read')
        try:
            path.replace(_backup_path(path))
        except OSError:
            _record_failure('modules/finance_watchlist.py:backup')
            raise OSError('Bozuk takip listesi yedeklenemedi.') from None
        return []
    except OSError:
        _record_failure('modules/finance_watchlist.py:read_io')
        raise OSError('Takip listesi okunamadı.') from None


def _save(path, rows):
    temporary = None
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary = tempfile.mkstemp(prefix='.finance-watchlist-', suffix='.tmp', dir=path.parent)
        with os.fdopen(fd, 'w', encoding='utf-8') as handle:
            json.dump(rows, handle, ensure_ascii=False)
            handle.flush()
            os.fsync(handle.fileno())
        for attempt in range(4):
            try:
                os.replace(temporary, path)
                temporary = None
                break
            except PermissionError:
                if attempt == 3:
                    raise
                time.sleep(0.02 * (attempt + 1))
    except OSError:
        _record_failure('modules/finance_watchlist.py:write')
        raise OSError('Takip listesi yazılamadı.') from None
    finally:
        if temporary is not None:
            try:
                Path(temporary).unlink(missing_ok=True)
            except OSError:
                _record_failure('modules/finance_watchlist.py:temporary_cleanup')


def add(owner, kind, symbol):
    symbol = _normalise(kind, symbol)
    item = {'kind': kind, 'symbol': symbol}
    with _lock:
        path = _path(owner)
        rows = _read(path)
        for row in rows:
            if row == item:
                return dict(row)
        if len(rows) >= _LIMIT:
            raise ValueError('Takip listesi dolu (en fazla 20).')
        rows.append(item)
        _save(path, rows)
        return dict(item)


def remove(owner, kind, symbol):
    symbol = _normalise(kind, symbol)
    with _lock:
        path = _path(owner)
        rows = _read(path)
        kept = [row for row in rows if not (row['kind'] == kind and row['symbol'] == symbol)]
        if len(kept) == len(rows):
            return False
        _save(path, kept)
        return True


def list_items(owner):
    with _lock:
        return [dict(row) for row in _read(_path(owner))]


def clear(owner):
    with _lock:
        path = _path(owner)
        rows = _read(path)
        if not path.exists():
            return len(rows)
        try:
            path.unlink()
        except OSError:
            _record_failure('modules/finance_watchlist.py:clear')
            raise OSError('Takip listesi temizlenemedi.') from None
        return len(rows)
