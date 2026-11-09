"""Tüm modüllerin paylaştığı LLM istemcisi (Google Gemini)."""
from modules.diagnostics import record_failure as _record_failure
import re
import time
import logging
import threading
from urllib.parse import urlparse

log = logging.getLogger("jarvis.llm")
from contextvars import ContextVar
from modules import failure_policy, requests_state, usage_meter

from google import genai
from google.genai import errors, types

from config import API_KEY, MODEL

try:
    from config import FALLBACK_MODELS
except ImportError:   # eski config.py ile de çalışsın
    FALLBACK_MODELS = ()

_client = genai.Client(api_key=API_KEY, http_options={"timeout": 45000}) if API_KEY else None


def set_api_key(key: str) -> None:
    """Çalışırken yeni Gemini anahtarına geçer (yeniden başlatma gerekmez)."""
    global _client
    _client = genai.Client(api_key=key.strip(), http_options={"timeout": 45000})


# ---------------------------------------------------------------- kişiye özel anahtar (isteğe bağlı)
# Her kullanıcı kendi Gemini anahtarını kullanır; kullanıcılar arasında ortak/fallback anahtar YOKTUR.
# main.py o an konuşan kullanıcıyı istek bağlamına yazar. Global istemci yalnız kullanıcı bağlamı olmayan
# bakım/ilk-kurulum işlemleri içindir; normal kullanıcı sohbetinde kullanılmaz.
_key_context = ContextVar("jarvis_llm_user", default=None)
def current_user():
    target = _key_context.get()
    if target is not None:
        return target
    from modules.personalization import get_active, slugify
    return slugify(get_active()) or None
_user_clients: dict = {}            # kullanıcı -> (anahtar, istemci)
_client_lock = threading.RLock()


def set_user_context(slug: str | None) -> str | None:
    """Tüm modüller için tek aktif kullanıcı/API bağlamı giriş noktası.

    UI, sistem taraması, Çalışma ve Vision kullanıcı anahtarı
    çözerken bu bağlamı kullanır. Başka kullanıcının anahtarına fallback yapılmaz.
    """
    target = (str(slug).strip() if slug else None) or None
    _key_context.set(target)
    return target


def key_state(slug: str | None = None) -> dict:
    """UI ve tanılama için merkezi Gemini anahtar durumu; anahtarı dışarı sızdırmaz."""
    target = (str(slug).strip() if slug else current_user()) or None
    k = user_key(target) if target else ""
    return {"user": target or "", "configured": bool(k), "provider": provider()}


def _key_file(slug: str):
    from config import DATA_DIR
    return DATA_DIR / "keys" / f"{slug}.txt"


def user_key(slug: str | None) -> str:
    if not slug:
        return ""
    f = _key_file(slug)
    try:
        return privacy.unprotect(f.read_text(encoding="utf-8")).strip() if f.exists() else ""
    except (OSError, ValueError):
        _record_failure('modules/llm.py:user_key')  # privacy-safe diagnostic is emitted at the catch boundary
        return ""


def set_user_key(slug: str, key: str | None) -> None:
    """Kullanıcının kendi anahtarını korumalı kaydeder; boş verilirse yalnız o kullanıcının anahtarı silinir."""
    f = _key_file(slug)
    with _client_lock:
        if key and key.strip():
            f.parent.mkdir(exist_ok=True)
            f.write_text(privacy.protect(key.strip()), encoding="utf-8")
        elif f.exists():
            f.unlink()
        _user_clients.pop(slug, None)



def _groq_key_file(slug: str):
    from config import DATA_DIR
    return DATA_DIR / "keys" / f"{slug}.groq.txt"


def user_groq_key(slug: str | None) -> str:
    """Yalnız belirtilen kullanıcının Groq anahtarı; ortak fallback yoktur."""
    if not slug:
        return ""
    f = _groq_key_file(slug)
    try:
        return privacy.unprotect(f.read_text(encoding="utf-8")).strip() if f.exists() else ""
    except Exception:
        _record_failure('modules/llm.py:user_groq_key')
        return ""


def set_user_groq_key(slug: str, key: str | None) -> None:
    f = _groq_key_file(slug)
    if key and key.strip():
        f.parent.mkdir(exist_ok=True)
        f.write_text(privacy.protect(key.strip()), encoding="utf-8")
    elif f.exists():
        f.unlink()
def _cli():
    """Normal kullanıcı sohbetinde SADECE o kullanıcının Gemini anahtarını döndürür.

    Kullanıcı bağlamı yoksa (bakım/ilk kurulum gibi) global istemci kullanılabilir.
    Bir kullanıcının anahtarı yoksa başka kullanıcının veya ortak anahtarın kotasını
    tüketmemek için None döner.
    """
    slug = current_user()
    if not slug:
        return _client
    with _client_lock:
        cached = _user_clients.get(slug)
        if cached is None:
            k = user_key(slug)
            cached = (k, genai.Client(api_key=k, http_options={"timeout": 45000}) if k else None)
            _user_clients[slug] = cached
        return cached[1]


# ---------------------------------------------------------------- sağlayıcı: Gemini (bulut) / Ollama (yerel)
import requests

from config import load_settings, save_settings
from modules import ollama_hint, privacy


class LocalModelError(RuntimeError):
    """Ollama'ya ulaşılamadı ya da model yok."""

class ImageCapabilityError(LocalModelError):
    """Ollama modeli çalışıyor fakat görüntü girdisini desteklemiyor."""


# Yerel model sunucusu: "ollama" sağlayıcısı yuvası aynı kalır, arkadaki sunucu seçilebilir.
# LM Studio ve llama.cpp (llama-server) OpenAI uyumlu /v1 uç noktası sunar; ikisi de isteğe bağlıdır.
LOCAL_BACKENDS = {"ollama": "http://127.0.0.1:11434", "lmstudio": "http://127.0.0.1:1234/v1",
                  "llamacpp": "http://127.0.0.1:8080/v1"}
LOCAL_LABELS = {"ollama": "Ollama", "lmstudio": "LM Studio", "llamacpp": "llama.cpp"}


def _choice() -> dict:
    """Aktif kullanıcının kendi sağlayıcı/model seçimi (yoksa boş: kurulum ayarı geçerli)."""
    from modules import user_models
    return user_models.choice(current_user())


def _cfg() -> dict:
    s = load_settings()
    mine = _choice()
    configured = mine.get("provider") or s.get("provider") or "gemini"
    if configured not in {"auto", "gemini", "groq", "ollama", "openai", "anthropic"}:
        configured = "auto"   # unknown or removed provider names fall back to the router policy
    backend = s.get("local_backend") if s.get("local_backend") in LOCAL_BACKENDS else "ollama"
    if backend == "ollama":
        url, model = s.get("ollama_url") or LOCAL_BACKENDS["ollama"], mine.get("local_model") or s.get("ollama_model") or "llama3.2"
    else:   # model boşsa sunucunun /models listesindeki ilk model kullanılır (_local_model)
        url, model = s.get("local_url") or LOCAL_BACKENDS[backend], (mine.get("local_model") or s.get("local_model") or "").strip()
    return {"provider": configured, "backend": backend, "url": url.rstrip("/"), "model": model}


def _backend(c: dict | None = None) -> str:
    return (c if c is not None else _cfg()).get("backend", "ollama")


def local_info() -> dict:
    """Ağ çağrısı yapmadan seçili yerel sunucu bilgisi (arayüz anlık görüntüsü için)."""
    c = _cfg()
    return {"local_backend": _backend(c), "local_label": LOCAL_LABELS[_backend(c)],
            "ollama_url": c["url"], "ollama_model": c["model"]}


def local_label() -> str:
    return LOCAL_LABELS[_backend()]


def local_hint() -> str:
    """Seçili yerel sunucu yokken tek Türkçe çözüm cümlesi."""
    backend = _backend()
    if backend == "ollama":
        return ollama_hint.need("Yerel model")
    return ollama_hint.need_local(LOCAL_LABELS[backend], _cfg()["url"])


GROQ_MODELS = ["openai/gpt-oss-120b", "openai/gpt-oss-20b", "qwen/qwen3.8-27b"]
_DEPRECATED_GROQ = {"llama-3.3-70b-versatile", "llama-3.1-8b-instant", "qwen/qwen3.6-27b"}
_GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"


def groq_model() -> str:
    """Etkin Groq modeli. Eski/deprecated ücretsiz modelleri güvenli varsayılana taşır."""
    model = (_choice().get("groq_model") or load_settings().get("groq_model") or "").strip()
    if not model or model in _DEPRECATED_GROQ:
        return GROQ_MODELS[0]
    return model


def provider() -> str:
    """Şu an kullanılacak sağlayıcı: gemini | groq | ollama. Yerel gizlilik modu daima Ollama'dır."""
    return "ollama" if privacy.mode() == "yerel" else _cfg()["provider"]


def gemini_aux_allowed() -> bool:
    """Provider Routing Policy v1: embed, STT, vision and Live carry private content (documents, voice,
    screen), so none of them may reach Gemini. Gemini is only the PUBLIC_RESEARCH route (``research``)."""
    return False


def _cloud_confirmed() -> bool:
    """Owner confirmed the free-account policy (used for key-health checks that send no user content)."""
    if provider() != 'auto': return True
    from modules import smart_router
    return bool(smart_router.settings(current_user()).get('cloud_free_confirmed'))


_ollama_tags_lock = threading.Lock()
_ollama_tags_cache = {}


def ollama_models(force=False) -> list[str]:
    """Seçili yerel sunucudaki modeller (Ollama /api/tags, LM Studio/llama.cpp /models); yoksa boş liste."""
    c = _cfg()
    url, openai_like = c['url'], _backend(c) != "ollama"
    with _ollama_tags_lock:
        cached = _ollama_tags_cache.get(url)
        # Kurulu olmayan (boş) sonuç daha uzun tutulur: kapalı yerel porta bağlanmak Windows'ta saniyeler sürebilir.
        if not force and cached and time.monotonic() - cached[0] < (3 if cached[1] else 20):
            return list(cached[1])
        try:
            host = (urlparse(url).hostname or '').lower()
            connect = 0.4 if host in ('127.0.0.1', 'localhost', '::1') else 3   # yerel Ollama yoksa açılışı bekletme
            r = requests.get(url + ('/models' if openai_like else '/api/tags'), timeout=(connect, 3))
            r.raise_for_status()
            if openai_like:
                rows = sorted(m['id'] for m in r.json().get('data', []) if isinstance(m.get('id'), str))
            else:
                rows = sorted(m['name'] for m in r.json().get('models', []) if isinstance(m.get('name'), str))
        except (requests.RequestException, ValueError, TypeError, AttributeError):
            rows = []
        if len(_ollama_tags_cache) >= 8:
            _ollama_tags_cache.clear()
        _ollama_tags_cache[url] = (time.monotonic(), rows)
        return list(rows)


def _installed_ollama_name(model: str, installed: list[str]) -> str | None:
    """Resolve only the default :latest alias; return a real installed identifier."""
    model=(model or '').strip()
    if model in installed:return model
    if ':' not in model.rsplit('/',1)[-1] and model:
        alias=model+':latest'
    elif model.endswith(':latest'):
        alias=model[:-7]
    else:
        return None
    return alias if alias in installed else None


def _ollama_effective_model(c: dict, requested: str | None = None, *, refresh_missing: bool = True) -> str:
    """Resolve Ollama runtime model against models actually installed on the endpoint.

    A saved user preference remains stored, but only an installed model may become
    runtime authority. LM Studio/llama.cpp keep their existing resolution path.
    """
    if _backend(c) != "ollama":
        return requested or _local_model(c)
    rows = sorted(dict.fromkeys(ollama_models()))
    if not rows and refresh_missing:
        rows = sorted(dict.fromkeys(ollama_models(force=True)))
    if not rows:
        raise LocalModelError(local_hint())
    requested = (requested or "").strip()
    if resolved:=_installed_ollama_name(requested,rows):
        return resolved
    mine = _choice()
    user_model = (mine.get("local_model") or "").strip()
    if user_model:
        return _installed_ollama_name(user_model,rows) or rows[0]
    setting_model = (load_settings().get("ollama_model") or "").strip()
    if resolved:=_installed_ollama_name(setting_model,rows):
        return resolved
    return rows[0]


def model_check(force=False):
    from modules import model_health
    if privacy.mode() in ("gizli", "yerel"):
        return {"state":"private", "message":"Gizli/yerel modda bulut model kontrolü kapalı."}
    if not _cloud_confirmed():
        return {'state':'budget','message':'Smart Router: Gemini ücretsiz hesap doğrulaması yok; bulut model kontrolü yapılmadı.'}
    owner = current_user() or ''
    return model_health.check(owner, user_key(owner), model_names(owner), genai.Client, force)
def model_check_background():
    import threading
    owner = current_user()
    def run():
        set_user_context(owner)
        model_check()
    threading.Thread(target=run, daemon=True, name='model-check').start()
def paid_status() -> dict:
    from modules import paid_providers
    owner=current_user()
    return {name:paid_providers.status(owner,name) for name in paid_providers.PROVIDERS} if owner else {}


def status() -> dict:
    c = _cfg()
    om = ollama_models()
    from modules import model_health
    validation = model_health.cached(current_user() or "", user_key(current_user()), model_names())
    import config
    return {"groq_key": bool(user_groq_key(current_user())), "groq_model": groq_model(), "groq_models": GROQ_MODELS,
            "provider": provider(), "configured": c["provider"], "privacy": privacy.mode(),
            "model_validation": validation, "gemini_models": model_names(), "gemini_active": active_model(), "gemini_key": bool(user_key(current_user())),
            "paid": paid_status(),
            "ollama_url": c["url"], "ollama_model": c["model"], "ollama_up": bool(om), "ollama_models": om,
            "local_backend": _backend(c), "local_label": LOCAL_LABELS[_backend(c)], "local_backends": LOCAL_LABELS}


def set_local_backend(backend: str, url: str = "", model: str = "") -> None:
    """Yerel model sunucusunu seçer (Ollama, LM Studio, llama.cpp). Sağlayıcı seçimini değiştirmez."""
    if backend not in LOCAL_BACKENDS:
        raise ValueError("Yerel sunucu ollama, lmstudio veya llamacpp olmalı.")
    url = (url or "").strip().rstrip("/")
    if url:
        parsed = urlparse(url)
        if parsed.scheme not in ("http", "https") or not parsed.hostname:
            raise ValueError("Yerel uç nokta http://adres:port biçiminde olmalı.")
    ch = {"local_backend": backend}
    if backend == "ollama":
        if url: ch["ollama_url"] = url
        if model.strip(): ch["ollama_model"] = model.strip()
    else:
        ch["local_url"] = url or LOCAL_BACKENDS[backend]
        ch["local_model"] = model.strip() or None
    save_settings(**ch)


def set_provider(name: str, model: str | None = None, url: str | None = None) -> None:
    if name not in ("auto", "gemini", "ollama", "groq", "openai", "anthropic"):
        raise ValueError("Sağlayıcı gemini, groq, ollama, openai veya anthropic olmalı.")
    if name == "groq" and not user_groq_key(current_user()):
        raise ValueError("Bu kullanıcı için önce Groq API anahtarını Bağlantılar sayfasından ekle.")
    if name in ('openai','anthropic'):
        from modules import paid_providers
        owner=current_user()
        if not paid_providers.key(owner,name):raise ValueError('Önce kendi '+name+' API anahtarını Bağlantılar bölümünden ekle.')
        state=paid_providers.settings(owner,name)
        chosen=(model or state['candidate_model'] or state['model']).strip()
        if not chosen:raise ValueError('Önce model seç.')
        paid_providers.configure(owner,name,model=chosen)
    owner = current_user()
    if owner:
        # Seçim yalnız bu kullanıcıya yazılır; başka kullanıcının sağlayıcısı değişmez.
        choose_model(owner, name if model and name in ("groq", "ollama") else "", model or "")
        from modules import user_models
        user_models.save_choice(owner, provider=name)
        ch = {"ai_mode": name}
    else:
        ch = {"provider": name, "ai_mode": name}
        if model and name == "groq":
            ch["groq_model"] = model.strip()
        elif model and name == "ollama":
            ch["ollama_model"] = model.strip()
    if url:
        ch["ollama_url"] = url.strip()
    save_settings(**ch)


def _local_model(c: dict) -> str:
    """LM Studio/llama.cpp: ayarlı model yoksa sunucunun yüklü ilk modeli."""
    if c["model"]:
        return c["model"]
    rows = ollama_models()
    if not rows:
        raise LocalModelError(local_hint())
    return rows[0]


def _openai_local(messages: list[dict], system: str, max_tokens: int, images: list[str] | None = None,
                  model: str | None = None) -> str:
    """LM Studio ve llama.cpp: OpenAI uyumlu /chat/completions. Anahtar gerekmez, veri bilgisayardan çıkmaz."""
    c = _cfg()
    backend = _backend(c)
    label = LOCAL_LABELS[backend]
    model = model or _local_model(c)
    msgs = ([{"role": "system", "content": system}] if system else []) + messages
    if images:
        msgs[-1] = {**msgs[-1], "content": [{"type": "text", "text": msgs[-1].get("content", "")}] + [
            {"type": "image_url", "image_url": {"url": "data:image/png;base64," + b}} for b in images]}
    sent = usage_meter.size(messages) + len(system or "")
    try:
        r = requests.post(c["url"] + "/chat/completions", timeout=transport_timeouts(5, 45),
                          json={"model": model, "messages": msgs, "stream": False, "max_tokens": max_tokens})
    except requests.RequestException as e:
        usage_meter.record(backend, model, sent, 0, 'baglanti')
        raise LocalModelError(local_hint()) from e
    if r.status_code == 404:
        usage_meter.record(backend, model, sent, 0, '404')
        raise LocalModelError(f"{label} sunucusunda “{model}” modeli yok veya yüklenmemiş. Modeli {label} içinde yükle.")
    if r.status_code >= 400:
        usage_meter.record(backend, model, sent, 0, str(r.status_code))
        try:
            detail = str((r.json() if r.content else {}).get('error', '')).casefold()
        except ValueError:
            detail = ''
        if images and any(word in detail for word in ('image', 'vision', 'multimodal', 'does not support', 'mmproj')):
            raise ImageCapabilityError(ollama_hint.IMAGE)
        raise LocalModelError(f"{label} hata verdi ({r.status_code}).")
    try:
        text = ((r.json().get("choices") or [{}])[0].get("message") or {}).get("content", "")
    except (ValueError, AttributeError, IndexError, TypeError) as e:
        usage_meter.record(backend, model, sent, 0, 'bozuk')
        raise LocalModelError(f"{label} yanıtı çözülemedi (geçersiz JSON).") from e
    text = text if isinstance(text, str) else ""
    usage_meter.record(backend, model, sent, len(text), 'ok' if text else 'bos')
    _route.model = model
    return text


def choose_model(owner, name: str, model: str) -> dict:
    """Sağlayıcıyı değiştirmeden kullanıcının Groq veya yerel modelini kaydeder."""
    from modules import user_models
    if name not in ("", "groq", "ollama"):
        raise ValueError("Model seçimi yalnız Groq ve yerel model için.")
    if not owner:
        raise ValueError("Kullanıcı bulunamadı.")
    if not name or not model.strip():
        return user_models.choice(owner)
    if name == "groq":
        return user_models.save_choice(owner, groq_model=model)
    return user_models.save_choice(owner, local_model=model)


def _ollama(messages: list[dict], system: str, max_tokens: int, images: list[str] | None = None,
            model: str | None = None) -> str:
    c = _cfg()
    if _backend(c) != "ollama":
        return _openai_local(messages, system, max_tokens, images=images, model=model)
    model = _ollama_effective_model(c, requested=model)
    msgs = ([{"role": "system", "content": system}] if system else []) + messages
    if images:
        msgs[-1] = {**msgs[-1], "images": images}
    try:
        r = requests.post(c["url"] + "/api/chat", timeout=transport_timeouts(5, 45),
                          json={"model": model, "messages": msgs, "stream": False,
                                "options": {"num_predict": max_tokens}})
    except requests.Timeout as e:
        usage_meter.record('ollama', model, usage_meter.size(msgs), 0, 'baglanti')
        raise LocalModelError(f"{local_label()} yanıtı zaman aşımına uğradı.") from e
    except requests.RequestException as e:
        usage_meter.record('ollama', model, usage_meter.size(msgs), 0, 'baglanti')
        raise LocalModelError(local_hint()) from e
    sent = usage_meter.size(msgs)
    if r.status_code == 404:
        usage_meter.record('ollama', model, sent, 0, '404')
        raise LocalModelError(f"Ollama'da “{model}” modeli yok. Terminalde `ollama pull {model}` yaz.")
    if r.status_code >= 400:
        usage_meter.record('ollama', model, sent, 0, str(r.status_code))
        detail = str((r.json() if r.content else {}).get('error','')).casefold()
        if any(word in detail for word in ('image', 'vision', 'multimodal', 'does not support')):
            raise ImageCapabilityError(ollama_hint.IMAGE)
        raise LocalModelError(f"Ollama hata verdi ({r.status_code}).")
    try:                     # başarı, yanıt gerçekten çözülünce yazılır; bozuk 200 yanıtı "ok" sayılmaz
        data = r.json()
        text = (data.get("message") or {}).get("content", "")
    except ValueError as e:
        usage_meter.record('ollama', model, sent, 0, 'bozuk')
        raise LocalModelError("Ollama yanıtı çözülemedi (geçersiz JSON).") from e
    usage_meter.record('ollama', model, sent, len(text) if isinstance(text, str) else 0, 'ok' if text else 'bos',
                       tokens=usage_meter.tokens_from(data))
    _route.model = model
    return text


OLLAMA_BIG_MODEL = "qwen2.5:7b"


def ollama_model_for(prompt: str) -> str:
    """Kod ve analizde yüklüyse büyük yerel model; sohbette kurulu effective yerel model."""
    c = _cfg()
    if _backend(c) != "ollama":      # LM Studio/llama.cpp: mevcut çözümleme davranışı korunur
        return c["model"]
    base = _ollama_effective_model(c)
    big = (load_settings().get("ollama_big_model") or OLLAMA_BIG_MODEL).strip()
    if not big or big == base:
        return base
    from modules import smart_router
    if smart_router.task_type(prompt) in ("code", "analysis") and big in ollama_models():
        return big
    return base


def _ollama_task(messages: list[dict], system: str, max_tokens: int, prompt: str) -> str:
    """Legacy direct-call compatibility; router production calls ``_ollama`` once."""
    c = _cfg(); base = _ollama_effective_model(c); model = ollama_model_for(prompt)
    if model != base and base:
        try:
            return _ollama(messages, system, max_tokens, model=model)
        except ImageCapabilityError:
            raise
        except LocalModelError:
            note_route(f"{model} yanıt vermedi, {base} kullanılıyor", False)
    return _ollama(messages, system, max_tokens, model=base or None)




class CloudError(RuntimeError):
    """Bulut sağlayıcısına ulaşılamadı / anahtar geçersiz."""



def transport_timeouts(connect: float, read: float) -> tuple[float, float]:
    """Kalan yerel bütçeyi aşmayan (bağlantı, okuma) soket zaman aşımları.

    Bunlar toplam deadline DEĞİLDİR. Asıl sınır requests_state bütçesidir: `llm._timed` hem
    her denemeden önce, hem yanıt döndükten sonra, hem de taşıma hata çıkışında denetler. Burada
    amaç yalnızca taşımanın o sınırın kat kat üstünde yaşamamasıdır — 12 sn'lik bir bütçe
    varken 30 sn okumaya izin vermek, gelmiş bir yanıtı çöpe çevirip "sağlayıcı yanıt
    vermedi" diye raporlatıyordu. Bütçe yoksa (ör. arka plan işleri) kendi sabitleri kalır;
    değerler tabana iner, sıfıra düşmez (0 anında zaman aşımı demek olurdu)."""
    remaining = requests_state.budget_remaining()
    if remaining is None:
        return (connect, read)
    ceiling = max(0.05, remaining)
    return (min(connect, ceiling), min(read, ceiling))


def _groq(messages: list[dict], system: str, max_tokens: int, *, model: str | None = None) -> str:
    """One Groq transport attempt for the router-decided model."""
    key = user_groq_key(current_user())
    if not key:
        raise CloudError("Bu kullanıcının Groq API anahtarı yok. Bağlantılar sayfasından ekle.")
    msgs = ([{"role": "system", "content": system}] if system else []) + [dict(m) for m in messages]
    headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
    model = model or groq_model()
    if _limited('groq', model) is not None:
        raise CloudError('Groq modeli kota beklemesinde.')
    body = {"model": model, "messages": msgs, "max_tokens": max_tokens, "temperature": 0.2}
    requests_state.check()
    try:
        r = requests.post(_GROQ_URL, headers=headers, json=body, timeout=transport_timeouts(5, 30))
    except requests.RequestException as e:
        usage_meter.record('groq', model, usage_meter.size(msgs), 0, 'baglanti')
        raise CloudError('Groq bağlantısı kurulamadı (' + type(e).__name__ + ')') from e
    usage_meter.observe_limits('groq', model, getattr(r, 'headers', None))
    if r.status_code != 200:
        usage_meter.record('groq', model, usage_meter.size(msgs), 0, str(r.status_code))
    if r.status_code in (401, 403):
        raise CloudError('Groq API anahtarı geçersiz ya da yetkisiz.')
    if r.status_code == 429:
        headers_in = getattr(r, 'headers', None) or {}
        daily = failure_policy.quota_exhausted_text(getattr(r, 'text', ''))
        _mark_limited('groq', model, 'HTTP 429', _limit_seconds(daily, headers_in.get('retry-after')))
        raise CloudError('Groq istek/token sınırına takıldı (HTTP 429).')
    if r.status_code != 200:
        raise CloudError('Groq yanıt vermedi (HTTP ' + str(r.status_code) + ')')
    try:
        data = r.json(); text = data["choices"][0]["message"]["content"]
        if not isinstance(text, str) or not text.strip():
            raise ValueError('empty answer')
    except (KeyError, IndexError, TypeError, ValueError) as e:
        usage_meter.record('groq', model, usage_meter.size(msgs), 0, 'bos')
        raise CloudError('Groq boş ya da geçersiz yanıt verdi.') from e
    usage_meter.record('groq', model, usage_meter.size(msgs), len(text), tokens=usage_meter.tokens_from(data))
    _route.model = model
    return text


def _need_cloud(prompt: str) -> str:
    """Buluta gitmeden önce: yerel modda engelle, değilse hassas bilgiyi maskele."""
    if privacy.mode() == "yerel":
        raise LocalModelError("Yalnızca yerel mod açık ama yerel model yanıt vermedi. " + ollama_hint.need("Bu mod"))
    return privacy.redact(prompt)


def embed(texts: list[str]) -> list[list[float]]:
    """Metin vektörleri (anlamsal arama). Belgeler/sorular özeldir: yalnız yerel Ollama; buluta (Gemini) gitmez."""
    c = _cfg()
    if _backend(c) != "ollama":
        raise ValueError("Yerel gömme (anlamsal arama) şimdilik yalnız Ollama ile çalışır.")
    model = load_settings().get("ollama_embed_model") or "nomic-embed-text"
    try:
        from modules import ollama_embed
        return ollama_embed.run(texts, c["url"], model)
    except (requests.RequestException, KeyError, ValueError, AttributeError) as e:
        raise ValueError("Yerel gömme modeli yok (`ollama pull nomic-embed-text`).") from e


_SWITCH_CODES = {404, 429, 500, 502, 503, 504}   # bunlarda bekleme/yedek modele geçiş denenir
_MODELS = [MODEL, *[m for m in FALLBACK_MODELS if m != MODEL]]
_MAX_TRIES = failure_policy.MAX_RETRIES   # aynı modele en fazla kaç deneme (araya artan bekleme: ~1, ~2 sn)
_MAX_TURNS = 8        # son kaç karşılıklı konuşma hatırlansın
_histories: dict[str, list] = {}   # kullanıcı -> sohbet geçmişi (kullanıcılar karışmasın)
_history_seed = None               # kullanıcı -> [(rol, metin)]: kalıcı geçmişten son konuşmalar (main ayarlar)
_history_lock = threading.RLock()
_history_epochs: dict[str, int] = {}
_draft_epochs = ContextVar("jarvis_chat_drafts", default=None)


def reset_history(user: str) -> None:
    """Invalidate in-flight drafts as well as the short conversation memory."""
    with _history_lock:
        _history_epochs[user] = _history_epochs.get(user, 0) + 1
        _histories[user] = []


def set_history_seed(fn) -> None:
    """Yazılı sohbetin hafızası açılışta boş başlamasın: ilk soruda kalıcı geçmişteki son konuşmalarla (sesli ve
    yazılı) doldurulur. Önce yeniden başlatınca ya da sesten yazıya geçince bağlam kopuyordu."""
    global _history_seed
    _history_seed = fn


def _seed(user: str) -> None:
    if _history_seed is None:
        return
    try:
        turns = list(_history_seed(user) or [])
    except Exception:
        _record_failure('modules/llm.py:_seed')
        turns = []
    merged: list = []
    for role, text in turns[-2 * _MAX_TURNS:]:
        r = "model" if role == "assistant" else "user"
        text = str(text or "").strip()
        if not text:
            continue
        if provider() != "ollama":
            text = privacy.redact(text)              # bulut geçmişine ham hassas bilgi girmesin
        if merged and merged[-1].role == r:          # Gemini roller sırayla ister: art arda aynı rolü birleştir
            prev = merged[-1].parts[0].text
            merged[-1] = types.Content(role=r, parts=[types.Part(text=prev + "\n" + text)])
        else:
            merged.append(types.Content(role=r, parts=[types.Part(text=text)]))
    while merged and merged[0].role != "user":
        merged.pop(0)
    if merged and merged[-1].role == "user":         # cevapsız kalan son söz: yeni soru zaten onu içerir
        merged.pop()
    _histories[user] = merged


def _daily_quota(e: Exception) -> bool:
    """Günlük kota dolduysa beklemek işe yaramaz, hemen yedek modele geçilir."""
    return failure_policy.quota_exhausted_text(e)


def _gemini_retry_after(e: Exception):
    """Gemini 429 gövdesindeki RetryInfo.retryDelay ("34s" / "34.5s") saniyesi; yoksa None."""
    details = getattr(e, "details", None)
    items = (details.get("error", details) if isinstance(details, dict) else {}).get("details") or []
    for item in items if isinstance(items, list) else []:
        delay = item.get("retryDelay") if isinstance(item, dict) else None
        if isinstance(delay, str) and delay.endswith("s"):
            return delay[:-1]
    m = re.search(r"retryDelay['\"]?\s*:\s*['\"]?(\d+(?:\.\d+)?)s", str(e))
    return m.group(1) if m else None


_fallback_lock = threading.Lock()
_fallback_states = {}
# 429 alan model bir süre hiç denenmez: dakikalık sınır 1-2 sn sonra açılmaz, her çağrıda yeniden
# denemek yalnız boşa istek ve gecikmedir. Anahtar: (kullanıcı, sağlayıcı, model) -> (bitiş, hata).
_rate_limited = {}


def _limit_seconds(daily: bool, retry_after=None) -> int:
    try:
        wait = int(float(retry_after))
    except (TypeError, ValueError):
        wait = 0
    if wait > 0:
        return max(5, min(wait, 3600))
    return 3600 if daily else 60


def _mark_limited(provider_name: str, model: str, error, seconds: int) -> None:
    with _fallback_lock:
        _rate_limited[(current_user(), provider_name, model)] = (time.monotonic() + seconds, error)


def _limited(provider_name: str, model: str):
    """Model hâlâ 429 beklemesindeyse kayıtlı hatayı döndürür, değilse None."""
    key = (current_user(), provider_name, model)
    with _fallback_lock:
        until, error = _rate_limited.get(key, (0, None))
        if until <= time.monotonic():
            _rate_limited.pop(key, None)
            return None
    return error


def quota_wait_seconds(owner=None) -> int:
    """Seçili sağlayıcıların hepsi 429/bekleme içindeyse kalan en kısa saniye; denenebilecek yol varsa 0."""
    owner = owner if owner is not None else current_user()
    name = provider()
    if name == 'auto':
        from modules import smart_router
        return smart_router.wait_seconds(owner)
    if name != 'gemini' or user_groq_key(owner):
        return 0                       # Groq/Ollama yedeği ya da başka sağlayıcı: denemeden bilemeyiz
    now = time.monotonic()
    with _fallback_lock:
        left = [int(until - now + .999) if until > now else 0
                for until in (_rate_limited.get((owner, 'gemini', m), (0, None))[0] for m in model_names(owner))]
    return min(left) if left and all(left) else 0


def model_names(owner=None):
    from modules import user_models
    return user_models.get(owner if owner is not None else current_user(), _MODELS)


def active_model(owner=None):
    owner = owner if owner is not None else current_user()
    names = model_names(owner)
    with _fallback_lock:
        idx, switched = _fallback_states.get((owner, tuple(names)), (0, 0))
    if idx >= len(names) or time.time()-switched>600:
        idx=0
    return names[idx]


def model_settings(owner, model, fallbacks):
    from modules import user_models
    current=model_names(owner)
    names=[model.strip() or current[0]] + list(fallbacks)
    user_models.save(owner, names)
    return model_names(owner)


def _metered(call, chars_in, kind='gemini'):
    call.chars_in, call.kind = chars_in, kind
    return call


def _with_models(call, *, model=None):
    """Compatibility for old direct callers; routed production passes ``model`` and calls once."""
    if model is not None:
        return call(model)
    chars_in, kind = getattr(call, 'chars_in', 0), getattr(call, 'kind', 'gemini')
    owner=current_user(); models=model_names(owner); last=None
    for selected in models:
        if (waiting := _limited('gemini', selected)) is not None:
            last = waiting; continue
        try:
            result = call(selected)
            usage_meter.record(kind, selected, chars_in, len(result) if isinstance(result, str) else 0,
                               tokens=getattr(_route, 'tokens', None))
            _route.model = selected
            return result
        except (errors.ServerError, errors.ClientError) as exc:
            last = exc; code = getattr(exc, 'code', None)
            usage_meter.record(kind, selected, chars_in, 0, usage_meter.outcome(exc))
            if code == 429:
                daily = _daily_quota(exc)
                _mark_limited('gemini', selected, exc, _limit_seconds(daily, None if daily else _gemini_retry_after(exc)))
                continue
            raise
    raise last or RuntimeError('Yanıt verecek model yapılandırılmamış.')


# Arayüzdeki AI Modelleri kartı için: gerçek isteklerin son cevap süresi (ek/deneme isteği atılmaz, kota harcamaz).
LAST_SEC: dict = {}


_LABELS = {"gemini": "Gemini", "groq": "Groq", "cloudflare": "Cloudflare", "ollama": "Ollama (yerel)",
           "openai": "OpenAI", "anthropic": "Claude"}
_route = threading.local()   # bu iş parçacığındaki isteğin model izi; yalnız sağlayıcı/model adı, metin yok


def provider_label(name: str) -> str:
    if name == "ollama" and _backend() != "ollama":
        return local_label() + " (yerel)"
    return _LABELS.get(name, name)


def _local_unavailable(error: BaseException) -> str | None:
    """Bağlantı reddi: seçili yerel sunucuya göre kurulum/başlatma cümlesi."""
    if not ollama_hint.unavailable(error):
        return None
    return ollama_hint.unavailable(error) if _backend() == "ollama" else local_hint()


def note_route(text: str, ok: bool) -> None:
    notes = getattr(_route, "notes", None)
    if notes is None:
        notes = _route.notes = []
    notes.append((text, ok))
    del notes[:-8]


def discard_success_routes():
    """A completed classification/model call is not a completed user goal."""
    _route.notes=[row for row in (getattr(_route,'notes',None) or []) if not row[1]]
    _route.model=None


def take_route() -> list[tuple[str, bool]]:
    """İsteğin model izini verir ve temizler: geçiş/hata satırları ve en son cevap veren model."""
    notes = getattr(_route, "notes", None) or []
    _route.notes = []
    _route.model = None
    last_ok = [n for n in notes if n[1]][-1:]
    return [n for n in notes if not n[1]] + last_ok


def _timed(name: str, fn):
    t0 = time.time()
    requests_state.check()
    _route.model = None
    try:
        out = fn()
    except Exception as error:
        _record_failure('modules/llm.py:_timed')
        # Hata çıkışında da aynı denetim, ama kapsam bilerek dar: SystemExit/KeyboardInterrupt gibi
        # süreç kontrol sinyalleri burada yakalanmaz, kendi gibi yukarı çıkar.
        # Geniş yakalamanın ilk ifadesi tanıdır: hata hangi yolla çıkarsa çıksın iz bırakılmış olur,
        # mesaj redakte edilir ve aynı yer/tür/konum 60 sn boyunca tekrar yazılmaz.
        # Bütçe ya da kullanıcı iptali hükmünü verdiyse kök neden odur, sağlayıcının HTTP hatası
        # değil. Tek istisna yerel deadline'dır: taşıma kesin bir kimlik/kota bulgusu getirdiyse
        # (401/403, 429, açık günlük kota) o bilgi LocalDeadline'ın altında kalmaz, aksi hâlde
        # anahtar/kota müdahalesi hiç işlenmez ve sıradaki tur aynı kapıya yeniden çarpar.
        # Gerçek bekleme/ağ hattında hüküm yerel deadline'ındır: smart_router cooldown yazmaz ve
        # sıradaki adayı denemez. Bütçe duruyorsa asıl hata türü ve mesajıyla aynen korunur.
        try:
            requests_state.check()
        except requests_state.Cancelled as verdict:
            raise verdict from error    # kullanıcı iptali her bulgunun üstündür
        except requests_state.LocalDeadline as verdict:
            if not failure_policy.is_definitive_provider_finding(error):
                raise verdict from error
        raise
    requests_state.check()
    LAST_SEC[name] = round(time.time() - t0, 1)
    model = getattr(_route, "model", None)
    note_route("Cevap: " + provider_label(name) + (f" · {model}" if model else ""), True)
    return out


_PAID = ('openai', 'anthropic')


def _send(prompt: str, system: str, max_tokens: int, history, route=None) -> str:
    """Text generation. Only the Router chooses a provider and decides every fallback; this function never
    switches provider by itself. An explicit paid choice (OpenAI/Claude) stays outside the automatic pool."""
    selected = provider()
    if selected in _PAID or selected == 'ollama':   # explicit paid or local-only choice: no automatic pool
        return _send_provider(selected, prompt, system, max_tokens, history)
    from modules import smart_router
    request = smart_router.ModelRequest(owner=current_user(), route=route,
        max_output_tokens=max_tokens, features=frozenset({'text'}))
    return smart_router.run_request(request,
        lambda spec: _send_provider(spec.provider, prompt, system, max_tokens, history, model=spec.model)).text


def _send_provider(name: str, prompt: str, system: str, max_tokens: int, history, *, model: str | None = None) -> str:
    """One provider, one attempt: transport only. No cross-provider fallback (the Router owns that)."""
    if name != 'ollama' and history:
        history = [types.Content(role=h.role,parts=[types.Part(text=privacy.redact(p.text)) for p in h.parts if getattr(p,'text',None)]) for h in history]
    if name in _PAID:
        from modules import paid_providers
        return _timed(name,lambda:paid_providers.generate(current_user(),name,
                      _ohist_msgs(history)+[{'role':'user','content':prompt}],system,max_tokens))
    if name == "groq":
        try:
            return _timed("groq", lambda: _groq(_ohist_msgs(history) + [{"role": "user", "content": privacy.redact(prompt)}],
                         privacy.redact(system), max_tokens, model=model))
        except CloudError as e:
            raise LocalModelError(str(e)) from e
    if name == "ollama":
        return _timed("ollama", lambda: _ollama(_ohist_msgs(history) + [{"role": "user", "content": prompt}], system, max_tokens, model=model))
    if name == "cloudflare":
        from modules import cloudflare_chat
        try:
            return _timed("cloudflare", lambda: cloudflare_chat.chat(
                _ohist_msgs(history) + [{"role": "user", "content": privacy.redact(prompt)}],
                privacy.redact(system), max_tokens, slug=current_user(), model=model or cloudflare_chat.MODEL))
        except cloudflare_chat.CloudflareChatError as e:
            raise LocalModelError(str(e)) from e
    if name != "gemini":
        raise ValueError("Bilinmeyen sağlayıcı.")
    prompt = _need_cloud(prompt)
    if _cli() is None:
        raise LocalModelError("Bu kullanıcının Gemini anahtarı yok.")
    system = privacy.redact(system)
    cfg = types.GenerateContentConfig(
        system_instruction=system or None,
        max_output_tokens=max_tokens,
        automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),   # araç çağrısı kullanmıyoruz
    )

    cli = [_cli()]

    chosen_model = model or active_model(current_user())
    def call(router_model=None) -> str:
        chat_session = cli[0].chats.create(model=router_model or chosen_model, config=cfg, history=history)
        resp = chat_session.send_message(prompt)
        _route.tokens = usage_meter.tokens_from(resp)
        return resp.text or ""

    def one_attempt():
        _route.tokens = None
        result = _with_models(call, model=model) if model is not None else _with_models(call)
        usage_meter.record('gemini', chosen_model, usage_meter.size(prompt, system, history),
                           len(result) if isinstance(result, str) else 0, tokens=getattr(_route, 'tokens', None))
        _route.model = chosen_model
        return result
    return _timed("gemini", one_attempt)


def _ohist_msgs(history) -> list[dict]:
    """Gemini geçmişini (types.Content) Ollama mesajlarına çevirir."""
    out = []
    for h in history or []:
        role = "assistant" if getattr(h, "role", "") == "model" else "user"
        txt = "".join(getattr(p, "text", "") or "" for p in (getattr(h, "parts", None) or []))
        if txt:
            out.append({"role": role, "content": txt})
    return out


def _observed(call: str, fn):
    """Model hook: metadata only (no prompt/answer text), never affects the call."""
    from modules import hooks
    started = time.time(); ok = False
    try:
        result = fn(); ok = True
        return result
    finally:
        hooks.observe("model", {"call": call, "provider": _provider_name(), "ok": ok,
                                "seconds": round(time.time() - started, 3)}, owner=current_user())


def _provider_name() -> str:
    try:
        return provider()
    except Exception:
        _record_failure('modules/llm.py:_provider_name')
        return "unknown"


def ask(prompt: str, system: str = "", max_tokens: int = 2000, *, validator=None) -> str:
    """Tek seferlik soru, geçmişi hatırlamaz (router ve araçlar için). Etiketsiz içerik daima PRIVATE rotadır."""
    return _observed("ask", lambda: _ask(prompt, system, max_tokens, validator=validator))


def research(query: str, evidence, system: str = "", max_tokens: int = 2000, *, validator=None) -> str:
    """Herkese açık araştırma: Gemini'ye giden tek kapı. Girdi yalnız maskelenmiş bağımsız sorgu ve etiketli
    kamuya açık kaynaklardır (geçmiş/hafıza/ek yok). Kaynaklardan biri bile PUBLIC etiketli değilse istek
    PRIVATE olur ve Gemini hiçbir hatada denenmez."""
    from modules import privacy_sources, provider_privacy
    items = list(evidence or [])
    public = privacy_sources.classify(items) is privacy_sources.RouteClass.PUBLIC
    route = provider_privacy.ROUTE_PUBLIC_RESEARCH if public else provider_privacy.ROUTE_PRIVATE_GENERAL
    parts = [str(getattr(item, "payload", item)) for item in items]
    prompt = privacy.redact(query) + ("\n\nKaynaklar:\n" + "\n\n".join(parts) if parts else "")
    return _observed("research", lambda: _ask(prompt, system, max_tokens, validator=validator, route=route))


def _ask(prompt: str, system: str = "", max_tokens: int = 2000, *, validator=None, route=None) -> str:
    if validator is not None:
        def checked(name, model=None):
            return _send_provider(name, prompt, system, max_tokens, None, model=model)
        if provider() in _PAID or provider() == 'ollama':
            answer = checked(provider())
            validator(answer)
            return answer
        from modules import smart_router
        request = smart_router.ModelRequest(owner=current_user(), route=route,
            max_output_tokens=max_tokens, features=frozenset({'text', 'structured_output'}))
        return smart_router.run_request(request,
            lambda spec: checked(spec.provider, spec.model), validator=validator).text
    return _send(prompt, system, max_tokens, None, route)


def chat(prompt: str, system: str = "", max_tokens: int = 2000, user: str = "default") -> str:
    """Önceki konuşmaları hatırlayan sohbet; her kullanıcının geçmişi ayrıdır."""
    text = chat_draft(prompt, system, max_tokens, user)
    commit_chat(prompt, text, user)
    return text


def chat_draft(prompt: str, system: str = "", max_tokens: int = 2000, user: str = "default") -> str:
    """Sohbet cevabını üretir ama geçmişe yazmaz (önceden hazırlanan cevap kullanılmazsa iz bırakmasın)."""
    with _history_lock:
        _seed(user)
        epoch = _history_epochs.get(user, 0)
        drafts = dict(_draft_epochs.get() or {})
        drafts[user] = epoch
        _draft_epochs.set(drafts)
        history = list(_histories.get(user, []))
    return _observed("chat", lambda: _send(prompt, system, max_tokens, history))


def commit_chat(prompt: str, text: str, user: str = "default") -> None:
    """chat_draft ile üretilen cevabı sohbet geçmişine ekler."""
    if not text:
        return
    with _history_lock:
        expected = (_draft_epochs.get() or {}).get(user, _history_epochs.get(user, 0))
        if expected != _history_epochs.get(user, 0):
            raise requests_state.Cancelled("Yeni sohbet açıldı; eski yanıt kullanılmadı.")
        requests_state.check()
        _seed(user)
        history = _histories.setdefault(user, [])
        stored = prompt if provider() == "ollama" else privacy.redact(prompt)
        history += [
            types.Content(role="user", parts=[types.Part(text=stored)]),
            types.Content(role="model", parts=[types.Part(text=text)]),
        ]
        del history[:-2 * _MAX_TURNS]


def ask_image(image_path: str, prompt: str, system: str = "", max_tokens: int = 2000, *, strict: bool = False) -> str:
    """Ekran/görüntü özeldir: yalnız yerel görüntü modeli (veya açıkça seçilmiş ücretli sağlayıcı); Gemini yok."""
    if privacy.mode() == 'gizli':
        if strict:raise PermissionError('Gizli modda görüntü analizi kapalı.')
        return 'Gizli modda görüntü analizi kapalı.'
    selected = provider()
    if selected in _PAID:
        return _ask_image(image_path,prompt,system,max_tokens,selected,strict=strict)
    from modules import smart_router
    if provider() == 'auto' or strict:
        return smart_router.run(current_user(), prompt, lambda name: _ask_image(image_path,prompt,system,max_tokens,name,True),image=True)
    return _ask_image(image_path,prompt,system,max_tokens,'ollama',strict=strict)


def _ask_image(image_path, prompt, system='', max_tokens=2000, selected=None, strict=False):
    """Transport only: one provider, no fallback. Images never go to a Gemini/Groq/Cloudflare cloud."""
    selected=selected or provider()
    requests_state.check()
    if privacy.mode() == "gizli":
        return "Gizli modda görüntü analizi kapalı."
    try:
        if selected in _PAID:
            from modules import paid_providers
            return _timed(selected,lambda:paid_providers.generate(current_user(),selected,
                          [{'role':'user','content':prompt}],system,max_tokens,image_path=image_path))
        if selected != "ollama":
            raise LocalModelError("Görüntü yalnızca yerel görüntü modeline gider.")
        import base64
        with open(image_path, "rb") as f:
            b64 = base64.b64encode(f.read()).decode()
        return _ollama([{"role": "user", "content": prompt}], system, max_tokens, images=[b64])
    except requests_state.Cancelled:
        raise
    except Exception as e:
        _record_failure('modules/llm.py:ask_image')
        if strict: raise
        return "Ekran resmi okunamadı: " + failure_policy.user_message(e)


def transcribe(audio_path: str | None = None, mime: str = "audio/wav", data: bytes | None = None,
               hints: list[str] | None = None) -> str:
    """Ses özeldir: Gemini'ye gönderilmez. Çağıranlar yerel/ücretsiz web STT'ye düşer."""
    raise RuntimeError("Ses kaydı buluta (Gemini) gönderilmez; yerel/web STT kullanılır.")


def gemini_client():
    """Current user's client (key isolation). Used only for key checks and the Live code PR9 removes;
    user content (documents, voice, screen) never goes through it: see ``gemini_aux_allowed``."""
    return _cli()


def provider_configuration():
    """Return a copy of the non-secret provider configuration for status consumers."""
    return dict(_cfg())


def test_groq():
    """Explicit connection test; saving a key alone does not imply this call."""
    return _groq([{"role":"user","content":"Sadece 'tamam' yaz."}], "", 20)
