"""Kullanıcıya özel, maskelenmiş yerel yönlendirme geri bildirimi; motor bağlantısı yok.

Dosya hataları tanılanır ve çağırana bildirilir; bozuk günlük sessizce ezilmez.
Dışa aktarılanlar yalnız Hamdi'nin inceleyeceği adaylardır, cümle setine yazılmaz.
"""
import json
import os
import re
import tempfile
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

from config import DATA_DIR
from modules import privacy
from modules.diagnostics import record_failure as _record_failure

_ROOT = DATA_DIR / 'misroute_logs'
_lock = threading.RLock()
_LIMIT = 500
_MAX_BYTES = 16_000_000
_SLUG = re.compile(r'[a-z0-9][a-z0-9_-]{0,99}')
_ROUTE = re.compile(r'[a-z][a-z0-9_]{0,39}')
_DEVICES = {'con', 'prn', 'aux', 'nul'} | {f'{p}{i}' for p in ('com', 'lpt') for i in range(1, 10)}


def _path(user_slug):
    if not isinstance(user_slug, str) or not _SLUG.fullmatch(user_slug) or user_slug in _DEVICES:
        raise ValueError('Geçerli, küçük harfli bir kullanıcı slug değeri gerekli.')
    path = _ROOT / f'{user_slug}.json'
    for item in (_ROOT, path):
        if item.is_symlink() or (hasattr(item, 'is_junction') and item.is_junction()):
            raise ValueError('Günlük yolu sembolik bağ veya junction olamaz.')
    return path


def _route(value, optional=False):
    if optional and value == '':
        return value
    if not isinstance(value, str) or not _ROUTE.fullmatch(value):
        raise ValueError('Kısa bir yol adı gerekli.')
    return value


def _clean(value, limit):
    if not isinstance(value, str):
        raise TypeError('Günlük metin alanları str olmalı.')
    # Önce maskele: kesilen bir anahtarın öneki diskte kalmasın.
    # Yan yana telefon/kartta ilk geçiş telefonu kaldırınca ikinci geçiş kartı görür.
    return privacy.redact(privacy.redact(value, force=True), force=True)[:limit]


def _read(path):
    try:
        with path.open('rb') as handle:
            raw = handle.read(_MAX_BYTES + 1)
        if len(raw) > _MAX_BYTES:
            raise ValueError('Günlük boyut sınırı aşıldı.')
        rows = json.loads(raw.decode('utf-8'))
        if not isinstance(rows, list) or len(rows) > _LIMIT:
            raise ValueError('Geçersiz günlük yapısı.')
        for row in rows:
            if (not isinstance(row, dict)
                    or not all(isinstance(row.get(k), str) for k in ('text', 'route', 'note', 'expected', 'ts'))
                    or type(row.get('wrong')) is not bool
                    or row.get('result') is not None and not isinstance(row['result'], str)):
                raise ValueError('Geçersiz günlük kaydı.')
            _route(row['route'])
            _route(row['expected'], optional=True)
        return rows
    except FileNotFoundError:
        return []
    except (OSError, UnicodeError, ValueError):
        _record_failure('modules/misroute_log.py:read')
        raise ValueError('Yönlendirme günlüğü okunamadı; mevcut dosya korunuyor.') from None


def _save(path, rows):
    temporary = None
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary = tempfile.mkstemp(prefix='.misroute-', suffix='.tmp', dir=path.parent)
        with os.fdopen(fd, 'w', encoding='utf-8') as handle:
            json.dump(rows[-_LIMIT:], handle, ensure_ascii=False)
            handle.flush()
            os.fsync(handle.fileno())
        for attempt in range(4):
            try:
                os.replace(temporary, path)
                break
            except PermissionError:
                if attempt == 3:
                    raise
                # Windows tarayıcı/antivirüs kilidi geçici olabilir; süre sınırlı.
                time.sleep(0.02 * (attempt + 1))
    except OSError:
        _record_failure('modules/misroute_log.py:write')
        raise OSError('Yönlendirme günlüğü yazılamadı.') from None
    finally:
        if temporary is not None:
            try:
                Path(temporary).unlink(missing_ok=True)
            except OSError:
                _record_failure('modules/misroute_log.py:temporary_cleanup')


def record(user_slug, text, route, result=None, note=''):
    """Son 500 kaydı yerelde tutar; sonuç isteğe bağlı kısa metindir."""
    route = _route(route)
    row = {'text': _clean(text, 4000), 'route': route,
           'result': None if result is None else _clean(result, 1000),
           'note': _clean(note, 1000), 'wrong': False, 'expected': '',
           'ts': datetime.now(timezone.utc).isoformat()}
    with _lock:
        path = _path(user_slug)
        rows = _read(path)
        rows.append(row)
        _save(path, rows)


def mark_wrong(user_slug, expected=''):
    """Son kaydı işaretler; kayıt yoksa False döndürür. Yol tahmin etmez."""
    expected = _route(expected, optional=True)
    with _lock:
        path = _path(user_slug)
        rows = _read(path)
        if not rows:
            return False
        rows[-1].update(wrong=True, expected=expected)
        _save(path, rows)
        return True


def export_candidates(user_slug):
    """Cümle seti alanlarını döndürür; boş etiketler insan incelemesi bekler.

    Veri setindeki model doğru sınıflandırıcı cevabıdır, gerçekleşen yanlış yol
    değildir. goal/task_agents görev etiketine çevrilir; smart_router tek başına
    niyet belirtmediğinden boş bırakılır. Hiçbir dosyaya veya servise gönderilmez.
    """
    with _lock:
        rows = _read(_path(user_slug))
        candidates = []
        for row in rows:
            if not row['wrong']:
                continue
            expected = {'goal': 'task', 'task_agents': 'task', 'smart_router': ''}.get(row['expected'], row['expected'])
            candidates.append({'metin': _clean(row['text'], 4000), 'model': expected,
                               'beklenen': expected, 'tartismali': True,
                               'kaynak': 'yerel yanlış yönlendirme günlüğü; Hamdi onayı bekliyor',
                               'gerceklesen_yol': row['route']})
        return candidates


def clear(user_slug):
    """Yalnız belirtilen kullanıcının günlük dosyasını kaldırır."""
    with _lock:
        path = _path(user_slug)
        try:
            path.unlink(missing_ok=True)
        except OSError:
            _record_failure('modules/misroute_log.py:clear')
            raise OSError('Yönlendirme günlüğü temizlenemedi.') from None
