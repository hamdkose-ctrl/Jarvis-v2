"""Kullanıcıya özel model tercihi: Gemini model sırası, sağlayıcı, Groq modeli ve yerel model.

Kayıt `~/.jarvis/models/<kullanıcı>.json`. Alan yoksa kurulumun genel ayarı (settings.json) geçerlidir.
Ücretli sağlayıcı yalnız kullanıcı açıkça seçerse buraya yazılır; buradan otomatik geçiş yapılmaz.
"""
from pathlib import Path
from copy import deepcopy
import re
import threading
import json
from config import DATA_DIR
import release_guard

_LOCK = threading.RLock()
PROVIDERS = ('auto', 'gemini', 'groq', 'ollama')
_GEMINI_NAME = r'[A-Za-z0-9._/-]{1,150}'
_MODEL_NAME = r'[A-Za-z0-9._:/@-]{1,150}'      # Ollama etiketi (llama3.2:3b) ve Groq kimliği (openai/gpt-oss-120b)
_CHOICE_KEYS = ('provider', 'groq_model', 'local_model')


def _path(owner):
    if not re.fullmatch(r'[\w-]{1,100}', str(owner or '')):
        raise ValueError('Kullanıcı bulunamadı.')
    return DATA_DIR / 'models' / (owner + '.json')


def _read(owner) -> dict:
    with _LOCK:
        try:
            value = json.loads(_path(owner).read_text(encoding='utf-8'))
        except FileNotFoundError:
            return {}
    if not isinstance(value, dict):
        raise ValueError('Model kaydı geçersiz.')
    return value


def get(owner, defaults):
    if not owner:
        return list(defaults)
    try:
        names = _read(owner).get('models')
        if names is None:          # yalnız sağlayıcı seçimi kayıtlı: Gemini sırası kurulum varsayılanı
            return list(defaults)
        if not isinstance(names, list) or not names or len(names)>8 or any(not isinstance(x,str) or not x.strip() for x in names):
            raise ValueError('Model kaydı geçersiz.')
        return list(dict.fromkeys(names))
    except (OSError, ValueError, AttributeError):
        from modules.diagnostics import record_failure
        record_failure('modules/user_models.py:get')
        return list(defaults)


def choice(owner) -> dict:
    """Kullanıcının kayıtlı sağlayıcı/Groq/yerel model seçimi; geçersiz veya eksik alanlar dönmez."""
    if not owner:
        return {}
    try:
        value = _read(owner)
    except (OSError, ValueError):
        from modules.diagnostics import record_failure
        record_failure('modules/user_models.py:choice')
        return {}
    out = {}
    stored = value.get('provider')
    if stored in ('openai','anthropic'):
        from modules import router_connections
        router_connections.migrate_legacy(owner)
        stored='auto'
    if stored in PROVIDERS:
        out['provider'] = stored
    elif stored is not None:
        # Unknown or removed provider name: fall back to the router policy and clear the stale record.
        out['provider'] = 'auto'
        try:
            _write(owner, provider='auto')
        except (OSError, ValueError):
            from modules.diagnostics import record_failure
            record_failure('modules/user_models.py:choice:migrate')
    for key in ('groq_model', 'local_model'):
        if isinstance(value.get(key), str) and re.fullmatch(_MODEL_NAME, value[key]):
            out[key] = value[key]
    return out


def _write(owner, **changes):
    def mutate(_routing,value):value.update(changes)
    update_routing(owner,mutate)


def routing(owner):
    value=_read(owner).get('routing_v2',{})
    if not isinstance(value,dict):raise ValueError('Router bağlantı kaydı bozuk.')
    return deepcopy(value)


def update_routing(owner,mutate):
    """One owner settings authority; OS claim protects concurrent process updates."""
    from modules import file_resource_guard
    path=_path(owner);path.parent.mkdir(parents=True,exist_ok=True)
    with _LOCK,file_resource_guard.claim_paths(path):
        value=_read(owner)
        routing=value.get('routing_v2',{})
        if not isinstance(routing,dict):raise ValueError('Router bağlantı kaydı bozuk.')
        result=mutate(routing,value)
        value['routing_v2']=routing
        release_guard.save(path,value)
        return result


def save(owner, names):
    if not isinstance(names,list) or not names or len(names)>8 or any(not isinstance(x,str) or not re.fullmatch(_GEMINI_NAME,x) for x in names):
        raise ValueError('Geçerli ana model ve en fazla 7 yedek model seç.')
    _write(owner, models=list(dict.fromkeys(names)))


def save_choice(owner, provider=None, groq_model=None, local_model=None):
    """Verilen alanları kullanıcıya yazar; None olan alan değişmez."""
    changes = {}
    if provider is not None:
        if provider not in PROVIDERS:
            raise ValueError('Sağlayıcı geçersiz.')
        changes['provider'] = provider
    for key, model in (('groq_model', groq_model), ('local_model', local_model)):
        if model is None:
            continue
        model = str(model).strip()
        if not re.fullmatch(_MODEL_NAME, model):
            raise ValueError('Model adı geçersiz.')
        changes[key] = model
    if changes:
        _write(owner, **changes)
    return choice(owner)
