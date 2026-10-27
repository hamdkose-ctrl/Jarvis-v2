"""Cached model discovery. It never guesses replacements or changes settings."""
from modules.diagnostics import record_failure as _record_failure
from modules import failure_policy
import hashlib
import logging
import threading
import time

log = logging.getLogger('jarvis.models')
_lock = threading.RLock()
_cache = {}

def _identity(owner, key, models):
    return owner, hashlib.sha256(key.encode()).hexdigest(), tuple(models)

def cached(owner, key, models):
    with _lock:
        hit = _cache.get(_identity(owner, key, models))
        return dict(hit[1]) if hit else {'state':'unchecked'}

def check(owner, key, models, client_factory, force=False):
    identity = _identity(owner,key,models)
    with _lock:
        hit = _cache.get(identity)
        if not force and hit and time.monotonic()-hit[0] < (3600 if hit[1]['state'] in ('ok','missing_models') else 120):
            return dict(hit[1])
    if not key:
        result={'state':'missing_key','message':'Bu kullanıcının Gemini anahtarı kayıtlı değil.'}
    else:
        client = None
        try:
            client=client_factory(api_key=key,http_options={'timeout':10000})
            available={str(m.name or '').removeprefix('models/') for m in client.models.list(config={'page_size':100})}
            missing=[m for m in models if m.removeprefix('models/') not in available]
            result={'state':'missing_models' if missing else 'ok','missing':missing,'checked_at':time.time(),
                    'message':('Models API listesinde bulunamadı: '+', '.join(missing)) if missing else 'Model adları Models API ile doğrulandı.'}
        except Exception as exc:
            _record_failure('modules/model_health.py:check')
            category = failure_policy.classify(exc)
            state = ('access_error' if category == failure_policy.AUTH else
                     'quota_error' if category in (failure_policy.RATE_LIMIT, failure_policy.QUOTA_EXHAUSTED) else
                     'connection_error')
            result={'state':state,'message':{'access_error':'Model listesine erişim reddedildi.','quota_error':'Model listesi için kullanım sınırına ulaşıldı.','connection_error':'Model listesi şu an doğrulanamadı.'}[state]}
        finally:
            if client is not None:
                try:client.close()
                except (AttributeError,OSError):pass
    with _lock:_cache[identity]=(time.monotonic(),result)
    return dict(result)
