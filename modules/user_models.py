"""Per-user Gemini model preference; the existing installation models remain defaults."""
from pathlib import Path
import re
import threading
import json
from config import DATA_DIR
import release_guard

_LOCK = threading.RLock()

def _path(owner):
    if not re.fullmatch(r'[\w-]{1,100}', str(owner or '')):
        raise ValueError('Kullanıcı bulunamadı.')
    return DATA_DIR / 'models' / (owner + '.json')


def get(owner, defaults):
    if not owner:
        return list(defaults)
    try:
        with _LOCK:
            value = json.loads(_path(owner).read_text(encoding='utf-8'))
        names = value.get('models')
        if not isinstance(names, list) or not names or len(names)>8 or any(not isinstance(x,str) or not x.strip() for x in names):
            raise ValueError('Model kaydı geçersiz.')
        return list(dict.fromkeys(names))
    except FileNotFoundError:
        return list(defaults)
    except (OSError, ValueError, AttributeError):
        from modules.diagnostics import record_failure
        record_failure('modules/user_models.py:get')
        return list(defaults)


def save(owner, names):
    if not isinstance(names,list) or not names or len(names)>8 or any(not isinstance(x,str) or not re.fullmatch(r'[A-Za-z0-9._/-]{1,150}',x) for x in names):
        raise ValueError('Geçerli ana model ve en fazla 7 yedek model seç.')
    with _LOCK:
        release_guard.save(_path(owner), {'models':list(dict.fromkeys(names))})
