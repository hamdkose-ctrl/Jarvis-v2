"""Kullanıcıya özel Sor/İzin ver/Engelle politikası; Harita bunu yazar, yürütme yolları okur.

Anahtar 'yol:sınıf' (ör. 'browser:publish'). Varsayılan ve bozuk/eksik dosya 'ask'
(kapının kendi kararı). 'deny' kesin retttir: kapı allow dese, izin veya onay olsa da.
'allow' yalnız yıkıcı yerel işte sorulanı açar; gönderim/yayın izni ve onayı değişmez.
Para/kimlik ve sistem ayarı sınıfları kilitlidir, politika onları değiştiremez.
"""
import json
import os
from pathlib import Path
import re
import tempfile
import threading

from config import DATA_DIR
from modules import service_store
from modules.diagnostics import record_failure as _record_failure

ROOT = Path(os.environ.get('JARVIS_HOME') or DATA_DIR) / 'permission_policy'
VALUES = ('ask', 'allow', 'deny')
LOCKED = ('money_credential', 'system_config')
_LOCK = threading.RLock()
_MAX_BYTES = 32000
_KEY = re.compile(r'[a-z0-9_]{1,40}:[a-z_]{1,40}')


def _path(user, *, verify=False):
    if verify:
        service_store.identity(user)
    if not isinstance(user, str) or not re.fullmatch(r'[a-z0-9][a-z0-9_-]{0,99}', user):
        raise ValueError('Geçersiz kullanıcı slug değeri.')
    for item in (ROOT / (user + '.json'), ROOT, *ROOT.parents):
        if item.is_symlink():
            raise ValueError('Politika kaydı yolu sembolik bağ olamaz.')
    return ROOT / (user + '.json')


def _read(path):
    try:
        data = json.loads(path.read_text(encoding='utf-8'))
    except (OSError, UnicodeError, ValueError):
        return {}
    if not isinstance(data, dict):
        return {}
    return {k: v for k, v in data.items()
            if isinstance(k, str) and _KEY.fullmatch(k) and v in VALUES}


def get(owner, via, action_class):
    """Kayıtlı politika; kilitli sınıf, eksik veya bozuk kayıt 'ask'."""
    if action_class in LOCKED:
        return 'ask'
    with _LOCK:
        return _read(_path(owner)).get(f'{via}:{action_class}', 'ask')


def set(owner, via, action_class, value):
    if value not in VALUES:
        raise ValueError('Geçersiz politika değeri.')
    if action_class in LOCKED:
        raise ValueError('Bu eylem sınıfı kilitli; politika değiştirilemez.')
    key = f'{via}:{action_class}'
    if not isinstance(via, str) or not isinstance(action_class, str) or not _KEY.fullmatch(key):
        raise ValueError('Geçersiz politika anahtarı.')
    with _LOCK:
        path = _path(owner, verify=True)
        data = _read(path)
        if value == 'ask':
            data.pop(key, None)
        else:
            data[key] = value
        raw = json.dumps(data, ensure_ascii=False, sort_keys=True).encode('utf-8')
        if len(raw) > _MAX_BYTES:
            raise ValueError('Politika kaydı boyut sınırı aşıldı.')
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary = tempfile.mkstemp(prefix='.permission-policy-', suffix='.tmp', dir=path.parent)
        try:
            with os.fdopen(fd, 'wb') as handle:
                handle.write(raw)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, path)
        finally:
            Path(temporary).unlink(missing_ok=True)


def apply(owner, via, action_class, decision, reason):
    """Kapının kararına politikayı uygular; (karar, gerekçe) döndürür. Hata çağıranda kapalı kalır."""
    policy = get(owner, via, action_class)
    if policy == 'deny':
        return 'deny', 'Politika: Engelle.'
    if policy == 'allow' and action_class == 'local_destructive' and decision == 'ask':
        return 'allow', 'Politika: İzin ver.'
    return decision, reason
