"""Tüm modüllerin paylaştığı LLM istemcisi (Google Gemini)."""
from modules.diagnostics import record_failure as _record_failure
import re
import hashlib
import time
import logging
import threading
from urllib.parse import urlparse

log = logging.getLogger("jarvis.llm")
from contextvars import ContextVar
from contextlib import contextmanager
from modules import failure_policy, requests_state, usage_meter

from google import genai
from google.genai import errors, types

from config import API_KEY, MODEL

try:
    from config import FALLBACK_MODELS
except ImportError:   # eski config.py ile de çalışsın
    FALLBACK_MODELS = ()

def _gemini_http_options(*, timeout_ms=45_000) -> dict:
    """One physical SDK HTTP attempt; Router owns all retries and fallbacks."""
    # Fresh per-client options: external client constructors must not mutate a
    # shared object and change another user's attempt budget.
    return {"timeout": timeout_ms, "retry_options": {"attempts": 1}}


GEMINI_MIN_DEADLINE_MS = 10_000


def _gemini_request_http_options() -> dict:
    """İstek başına SDK zaman aşımı; **10 sn tabanı** vardır.

    Canlı kusur (26 Kasım 16:46): kalan bütçe kısa olduğunda 3 s'lik bir deadline
    ayarlanıyordu ve Google isteği doğrudan reddediyordu:
    "Manually set deadline 3s is too short. Minimum allowed deadline is 10s."
    Kalan bütçe 10 sn'nin altındaysa SDK'ya süre verilmez; sınırı bizim bütçemiz
    ve iptal mekanizması uygular.
    """
    _, seconds = transport_timeouts(5, 45)
    if seconds * 1000 < GEMINI_MIN_DEADLINE_MS:
        return {"retry_options": {"attempts": 1}}
    return _gemini_http_options(timeout_ms=int(seconds * 1000))


_client = genai.Client(api_key=API_KEY, http_options=_gemini_http_options()) if API_KEY else None


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


@contextmanager
def owner_context(owner):
    token=_key_context.set(owner)
    try:yield
    finally:_key_context.reset(token)


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
            cached = (k, genai.Client(api_key=k, http_options=_gemini_http_options()) if k else None)
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
    if configured not in {"auto", "gemini", "groq", "ollama"}:
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
    """Auxiliary embed/STT operations keep their separate policy; typed vision has scoped consent."""
    return False


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
    owner = current_user() or ''
    return model_health.check(owner, user_key(owner), model_names(owner), genai.Client, force)
def model_check_background():
    import threading
    owner = current_user()
    def run():
        set_user_context(owner)
        model_check()
    threading.Thread(target=run, daemon=True, name='model-check').start()
def connection_status() -> list:
    from modules import router_connections
    owner=current_user()
    return router_connections.snapshot(owner) if owner else []


def status() -> dict:
    c = _cfg()
    om = ollama_models()
    from modules import model_health
    validation = model_health.cached(current_user() or "", user_key(current_user()), model_names())
    import config
    return {"groq_key": bool(user_groq_key(current_user())), "groq_model": groq_model(), "groq_models": GROQ_MODELS,
            "provider": provider(), "configured": c["provider"], "privacy": privacy.mode(),
            "model_validation": validation, "gemini_models": model_names(), "gemini_active": active_model(), "gemini_key": bool(user_key(current_user())),
            "custom_connections": connection_status(),
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
    if name not in ("auto", "gemini", "ollama", "groq"):
        raise ValueError("Özel sağlayıcıyı Özel API alanından bağlantı ve rol seçerek ekle.")
    if name == "groq" and not user_groq_key(current_user()):
        raise ValueError("Bu kullanıcı için önce Groq API anahtarını Bağlantılar sayfasından ekle.")
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
        data=r.json()
        text = ((data.get("choices") or [{}])[0].get("message") or {}).get("content", "")
    except (ValueError, AttributeError, IndexError, TypeError) as e:
        usage_meter.record(backend, model, sent, 0, 'bozuk')
        raise LocalModelError(f"{label} yanıtı çözülemedi (geçersiz JSON).") from e
    text = text if isinstance(text, str) else ""
    usage_meter.observe_response(data,finish_reason=(data.get('choices') or [{}])[0].get('finish_reason'))
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
        # `keep_alive`: Ollama modeli 5 dakika boşta boşaltıyor; sonraki turda
        # soğuk yükleme CPU yükü altında 45 sn'lik okuma süresini aşıyor ve yerel
        # yedek TAM O ANDA kaybediliyor (canlı: 23 Kasım 22:22 "Ollama yanıtı
        # zaman aşımına uğradı", ardından sağlayıcılar tükendi). Modeli yarım saat
        # sıcak tutmak soğuk yükleme cezasını kaldırır.
        r = requests.post(c["url"] + "/api/chat", timeout=transport_timeouts(5, 90),
                          json={"model": model, "messages": msgs, "stream": False,
                                "keep_alive": "30m",
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
    usage_meter.observe_response(data,finish_reason=data.get('done_reason'))
    usage_meter.record('ollama', model, sent, len(text) if isinstance(text, str) else 0, 'ok' if text else 'bos',
                       tokens=usage_meter.tokens_from(data))
    _route.model = model
    return text


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


def trim_for_request_limit(msgs: list[dict], keep: int = 4) -> list[dict] | None:
    """413 geldiğinde gövdeyi **bir kez** küçültür: sistem mesajı + son `keep` mesaj.

    Canlı ölçüm (26 Kasım): 12 istek 413 aldı ve aynı gövde yedek sağlayıcıya aynen
    gittiği için o da 413 veriyordu — yani yedek sağlayıcı hiç devreye girmiyordu.
    Kırpma sonrası hâlâ büyükse `None` döner: sonsuz tekrar yok.
    """
    rows = [m for m in msgs if isinstance(m, dict)]
    system = rows[:1] if rows and rows[0].get('role') == 'system' else []
    rest = rows[len(system):]
    if len(rest) <= keep:
        return None
    return system + rest[-keep:]


def _groq(messages: list[dict], system: str, max_tokens: int, *, model: str | None = None) -> str:
    """One Groq transport attempt for the router-decided model."""
    key = user_groq_key(current_user())
    if not key:
        raise CloudError("Bu kullanıcının Groq API anahtarı yok. Bağlantılar sayfasından ekle.")
    msgs = ([{"role": "system", "content": system}] if system else []) + [dict(m) for m in messages]
    headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
    model = model or groq_model()
    if _limited('groq', model,credential=key) is not None:
        raise CloudError('Groq modeli kota beklemesinde.')
    body = {"model": model, "messages": msgs, "max_tokens": max_tokens, "temperature": 0.2}
    requests_state.check()
    try:
        r = requests.post(_GROQ_URL, headers=headers, json=body, timeout=transport_timeouts(5, 30))
    except requests.RequestException as e:
        usage_meter.record('groq', model, usage_meter.size(msgs), 0, 'baglanti')
        raise CloudError('Groq bağlantısı kurulamadı (' + type(e).__name__ + ')') from e
    usage_meter.observe_limits('groq', model, getattr(r, 'headers', None),
                               credential=hashlib.sha256(key.encode()).hexdigest())
    if r.status_code != 200:
        usage_meter.record('groq', model, usage_meter.size(msgs), 0, str(r.status_code))
    if r.status_code in (401, 403):
        raise CloudError('Groq API anahtarı geçersiz ya da yetkisiz.')
    if r.status_code == 413:
        # Gövde çok büyükse **bir kez** kırpıp aynı sağlayıcıda yeniden dene; aksi hâlde
        # aynı dev gövde yedek sağlayıcıya gidip orada da 413 alıyordu (canlı 26 Kasım).
        trimmed = trim_for_request_limit(msgs)
        if trimmed is not None:
            usage_meter.record('groq', model, 0, 0, '413-trim')
            r = requests.post(_GROQ_URL, headers=headers,
                              json={**body, 'messages': trimmed}, timeout=transport_timeouts(5, 30))
    if r.status_code == 413:
        # Groq also uses 413 when one request exceeds its model's entire TPM
        # capacity. Preserve that finding without a raw body or provider cooldown.
        limit_kind = 'request_size'
        limit = requested = None
        try:
            payload = r.json()
        except ValueError:
            payload = None
        error = payload.get('error') if isinstance(payload, dict) else None
        if isinstance(error, dict) and error.get('code') == 'rate_limit_exceeded':
            message = error.get('message')
            message = message[:4096] if isinstance(message, str) else ''
            if re.search(r'\bTPM\b|tokens per minute', message, re.I):
                limit_kind = 'tokens_per_minute'
                counts = re.search(r'\bLimit\s+([0-9]{1,12})\s*,\s*Requested\s+([0-9]{1,12})\b', message, re.I)
                if counts:
                    limit, requested = map(int, counts.groups())
        raise failure_policy.ProviderRequestLimitError(provider='groq',status_code=413,
            limit_kind=limit_kind,limit=limit,requested=requested)
    if r.status_code == 429:
        headers_in = getattr(r, 'headers', None) or {}
        daily = failure_policy.quota_exhausted_text(getattr(r, 'text', ''))
        _mark_limited('groq', model, 'HTTP 429', _limit_seconds(daily, headers_in.get('retry-after')),credential=key)
        if daily:
            raise CloudError('Groq günlük kotası doldu (HTTP 429).')
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
    usage_meter.observe_response(data,finish_reason=data['choices'][0].get('finish_reason'))
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


def _limit_key(owner,provider_name,model,credential=None):
    from modules import smart_router
    fingerprint=smart_router._connection_fingerprint(owner,provider_name) if credential is None else hashlib.sha256(credential.encode()).hexdigest()
    return (owner,provider_name,model,fingerprint)


def _mark_limited(provider_name: str, model: str, error, seconds: int,*,credential=None) -> None:
    with _fallback_lock:
        _rate_limited[_limit_key(current_user(),provider_name,model,credential)] = (time.monotonic() + seconds, error)


def _limited(provider_name: str, model: str,*,credential=None):
    """Model hâlâ 429 beklemesindeyse kayıtlı hatayı döndürür, değilse None."""
    key = _limit_key(current_user(),provider_name,model,credential)
    with _fallback_lock:
        until, error = _rate_limited.get(key, (0, None))
        if until <= time.monotonic():
            _rate_limited.pop(key, None)
            return None
    return error


def quota_wait_seconds(owner=None) -> int:
    """The typed Router owns both configured free and custom/local waiting."""
    from modules import smart_router
    return smart_router.wait_seconds(owner if owner is not None else current_user())


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




# Arayüzdeki AI Modelleri kartı için: gerçek isteklerin son cevap süresi (ek/deneme isteği atılmaz, kota harcamaz).
LAST_SEC: dict = {}


_LABELS = {"gemini": "Gemini", "groq": "Groq", "cloudflare": "Cloudflare", "ollama": "Ollama (yerel)",'custom':'Özel API'}
_route = threading.local()   # bu iş parçacığındaki isteğin model izi; yalnız sağlayıcı/model adı, metin yok


def provider_label(name: str) -> str:
    if name == "ollama":
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


def _request(max_tokens,*,profile='long_worker',data_scope='selected_content',route=None,structured=False,evidence=None):
    from modules import smart_router
    owner=current_user()
    return smart_router.ModelRequest(owner=owner,request_id=requests_state.request_identity(owner) or '',
        profile=profile,data_scope=data_scope,route=route,evidence=evidence,
        selection_mode='local_only' if provider()=='ollama' else 'configured',
        work_class=requests_state.model_work_class() or ('background' if profile in ('long_worker','public_research') else 'interactive'),max_output_tokens=max_tokens,
        features=frozenset({'text','structured_output'} if structured else {'text'}))


BRAKE_STEP_SECONDS = 2.5
BRAKE_MAX_SECONDS = 20.0
BRAKE_PAY_SECONDS = 1.5   # fren bütçenin tamamını yemesin


def apply_rate_brake(spec, *, sleeper=None, deadline=None) -> float:
    """Ölçülmüş tavanın %90'ına yaklaşıldıysa kısa bekler (tek ağ kapısı: `dispatch`).

    Sayılar `modules/rate_limits.py` içinde kullanıcının kendi AI Studio ekranından
    ölçülmüş tavanlardır; model orada yoksa **hiç beklenmez** (uydurma limit yok).
    Bekleme sınırlıdır ve iptal her adımda denetlenir.
    """
    from modules import rate_limits, usage_meter
    if rate_limits.limit_for(getattr(spec, 'model', '')) is None:
        return 0.0
    sleep = sleeper or time.sleep
    # Canlı kusur (B-01): fren yalnız iptali denetliyordu, **kalan bütçeyi** değil.
    # `check_ready_connection` bütçesi 12 sn iken fren 20 sn bekleyebiliyor ve istek
    # kendi freniyle zaman aşımına düşüyordu. Bütçe yetmiyorsa beklememek doğrudur.
    allowed = BRAKE_MAX_SECONDS
    if deadline is not None:
        remaining = deadline - time.monotonic() - BRAKE_PAY_SECONDS
        allowed = min(BRAKE_MAX_SECONDS, max(0.0, remaining))
        if allowed < BRAKE_STEP_SECONDS:
            return 0.0
    waited = 0.0
    while waited + BRAKE_STEP_SECONDS <= allowed:
        rpm, tpm = usage_meter.recent_usage(getattr(spec, 'model', ''))
        if not rate_limits.should_wait(rpm, tpm, getattr(spec, 'model', '')):
            break
        requests_state.check()
        sleep(BRAKE_STEP_SECONDS)
        waited += BRAKE_STEP_SECONDS
    if waited:
        log.info("hız freni: %s için %.1f sn bekledim", getattr(spec, 'model', '?'), waited)
    return waited


def dispatch(request,spec,prompt,system,history=None,*,image_path=None):
    """One exact-model adapter boundary, including explicit owner custom connections."""
    apply_rate_brake(spec, deadline=getattr(request, 'deadline', None))
    token=_key_context.set(request.owner)
    try:
        requests_state.request_identity(request.owner)
        if spec.connection_id:
            from modules import router_connections,provider_protocols
            connection,secret=router_connections.resolve(request.owner,spec.connection_id,revision=spec.connection_revision)
            if connection['model']!=spec.model:raise ValueError('Bağlantı modeli değişti.')
            rows=_ohist_msgs(history)+[{'role':'user','content':prompt}]
            return provider_protocols.generate(request.owner,connection,secret,rows,system,
                                              request.max_output_tokens,image_path=image_path)
        if image_path is not None:
            return _image_transport(image_path,prompt,system,request.max_output_tokens,selected=spec.provider,model=spec.model)
        return _send_provider(spec.provider,prompt,system,request.max_output_tokens,history,model=spec.model)
    finally:_key_context.reset(token)


def _send(prompt: str, system: str, max_tokens: int, history, route=None,*,profile='conversation',data_scope='conversation') -> str:
    from modules import smart_router
    request=_request(max_tokens,profile=profile,data_scope=data_scope,route=route)
    return smart_router.run_request(request,lambda spec:dispatch(request,spec,prompt,system,history)).text


def _send_provider(name: str, prompt: str, system: str, max_tokens: int, history, *, model: str) -> str:
    """One provider, one attempt: transport only. No cross-provider fallback (the Router owns that)."""
    if name != 'ollama' and history:
        history = [types.Content(role=h.role,parts=[types.Part(text=privacy.redact(p.text)) for p in h.parts if getattr(p,'text',None)]) for h in history]
    if name == "groq":
        try:
            return _timed("groq", lambda: _groq(_ohist_msgs(history) + [{"role": "user", "content": privacy.redact(prompt)}],
                         privacy.redact(system), max_tokens, model=model))
        except CloudError as e:
            raise LocalModelError(str(e)) from e
    if name == "ollama":
        messages = _ohist_msgs(history) + [{"role": "user", "content": prompt}]
        return _timed("ollama", lambda:_ollama(messages, system, max_tokens, model=model))
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
    if not isinstance(model,str) or not model.strip():raise ValueError('Exact model Router tarafından seçilmeli.')
    prompt = _need_cloud(prompt)
    if _cli() is None:
        raise LocalModelError("Bu kullanıcının Gemini anahtarı yok.")
    system = privacy.redact(system)
    config_options = {
        "system_instruction": system or None,
        "max_output_tokens": max_tokens,
        "http_options": _gemini_request_http_options(),
        "automatic_function_calling": types.AutomaticFunctionCallingConfig(disable=True),
    }
    # Newer SDKs can continue a single send_message with extra HTTP requests.
    # Disable that feature where available; older SDKs do not expose it.
    if "automatic_continuation" in getattr(types.GenerateContentConfig, "model_fields", {}):
        config_options["automatic_continuation"] = False
    cfg = types.GenerateContentConfig(**config_options)

    cli = [_cli()]

    chosen_model = model
    def call(router_model=None) -> str:
        chat_session = cli[0].chats.create(model=router_model or chosen_model, config=cfg, history=history)
        try:
            resp = chat_session.send_message(prompt)
        except Exception as exc:
            _record_failure('modules/llm.py:_send_provider:gemini_transport')
            # Canlı kusur (26 Kasım 13:39): 400 Bad Request gövdesi log'a düşmüyordu,
            # kök neden görülemiyordu. Gövdeyi kısaltarak yaz.
            log.warning("gemini istek reddedildi: %s | %s", type(exc).__name__, str(exc)[:1500])
            # Routed Gemini calls otherwise lose failed attempts from the meter.
            if model is not None:
                usage_meter.record('gemini', router_model or chosen_model,
                                   usage_meter.size(prompt, system, history), 0,
                                   usage_meter.outcome(exc))
            raise
        _route.tokens = usage_meter.tokens_from(resp)
        candidates=getattr(resp,'candidates',None)
        usage_meter.observe_response(resp,finish_reason=getattr(candidates[0],'finish_reason',None) if candidates else None)
        return resp.text or ""

    call.chars_in = usage_meter.size(prompt, system, history)
    call.kind = 'gemini'
    def one_attempt():
        _route.tokens = None
        result = call(model)
        if model is not None:
            usage_meter.record('gemini', chosen_model, usage_meter.size(prompt, system, history),
                               len(result) if isinstance(result, str) else 0,
                               tokens=getattr(_route, 'tokens', None))
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


def ask(prompt: str, system: str = "", max_tokens: int = 2000, *, validator=None,profile='long_worker',
        evidence=None) -> str:
    """Tek seferlik soru, geçmişi hatırlamaz (router ve araçlar için).

    Etiketsiz içerik daima PRIVATE rotadır. ``evidence`` verilirse rota sınıfı o kanıtın
    provenansından gelir (hepsi gerçek, izinli PUBLIC değilse PRIVATE)."""
    return _observed("ask", lambda: _ask(prompt, system, max_tokens, validator=validator,profile=profile,
                                         evidence=evidence))


def research(query: str, evidence, system: str = "", max_tokens: int = 2000, *, validator=None) -> str:
    """Kaynak provenansı doğrulanan araştırma. Girdi yalnız maskelenmiş bağımsız sorgu ve etiketli
    kamuya açık kaynaklardır (geçmiş/hafıza/ek yok). Kaynaklardan biri bile PUBLIC etiketli değilse istek
    PRIVATE olur ve Gemini seçilmiş içerik iznine bağlıdır."""
    from modules import privacy_sources, provider_privacy
    items = list(evidence or [])
    public = privacy_sources.classify(items) is privacy_sources.RouteClass.PUBLIC
    route = provider_privacy.ROUTE_PUBLIC_RESEARCH if public else provider_privacy.ROUTE_PRIVATE_GENERAL
    parts = [str(getattr(item, "payload", item)) for item in items]
    prompt = privacy.redact(query) + ("\n\nKaynaklar:\n" + "\n\n".join(parts) if parts else "")
    return _observed("research", lambda: _ask(prompt, system, max_tokens, validator=validator, route=route,
        profile='public_research',data_scope='public' if public else 'selected_content'))


def _ask(prompt: str, system: str = "", max_tokens: int = 2000, *, validator=None, route=None,
         profile='long_worker',data_scope='selected_content',evidence=None) -> str:
    from modules import smart_router
    request=_request(max_tokens,profile=profile,data_scope=data_scope,route=route,structured=validator is not None,
                     evidence=evidence)
    return smart_router.run_request(request,lambda spec:dispatch(request,spec,prompt,system),validator=validator).text


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
    """Selected content keeps its private provenance; owner consent gates cloud vision."""
    if privacy.mode() == 'gizli':
        if strict:raise PermissionError('Gizli modda görüntü analizi kapalı.')
        return 'Gizli modda görüntü analizi kapalı.'
    selected = provider()
    from modules import smart_router
    request=smart_router.ModelRequest(owner=current_user(),profile='local_only' if selected=='ollama' else 'vision',
        data_scope='selected_content',features=frozenset({'vision'}),max_output_tokens=max_tokens,
        work_class=requests_state.model_work_class() or 'interactive')
    try:
        return smart_router.run_request(request,lambda spec:dispatch(request,spec,prompt,system,image_path=image_path)).text
    except (requests_state.Cancelled,requests_state.LocalDeadline):raise
    except Exception as exc:
        _record_failure('modules/llm.py:vision_request')
        if strict:raise
        return 'Görüntü analizi yapılamadı: '+failure_policy.user_message(exc)


def _image_transport(image_path, prompt, system, max_tokens, *, selected, model):
    """Transport only; the Router pins exact model and selected-content admission."""
    requests_state.check()
    if privacy.mode() == "gizli":
        raise PermissionError("Gizli modda görüntü analizi kapalı.")
    try:
        if selected=='gemini':
            if not model:raise ValueError('Görüntü modeli Router tarafından seçilmeli.')
            from pathlib import Path
            import mimetypes
            path=Path(image_path)
            mime=mimetypes.guess_type(str(path))[0]
            if mime not in ('image/png','image/jpeg','image/webp') or not 0<path.stat().st_size<=20*1024*1024:
                raise ValueError('Görüntü biçimi veya boyutu desteklenmiyor.')
            data=path.read_bytes()
            cli=_cli()
            if cli is None:raise LocalModelError('Bu kullanıcının Gemini anahtarı yok.')
            options={'system_instruction':privacy.redact(system) or None,'max_output_tokens':max_tokens,
                     'http_options':_gemini_request_http_options(),
                     'automatic_function_calling':types.AutomaticFunctionCallingConfig(disable=True)}
            if 'automatic_continuation' in getattr(types.GenerateContentConfig,'model_fields',{}):
                options['automatic_continuation']=False
            def call():
                try:
                    response=cli.models.generate_content(model=model,
                        contents=[types.Part.from_text(text=privacy.redact(prompt)),types.Part.from_bytes(data=data,mime_type=mime)],
                        config=types.GenerateContentConfig(**options))
                except Exception as exc:
                    _record_failure('modules/llm.py:gemini_vision_transport')
                    usage_meter.record('gemini',model,len(prompt),0,usage_meter.outcome(exc));raise
                candidates=getattr(response,'candidates',None)
                usage_meter.observe_response(response,finish_reason=getattr(candidates[0],'finish_reason',None) if candidates else None)
                text=response.text or ''
                usage_meter.record('gemini',model,len(prompt),len(text),tokens=usage_meter.tokens_from(response))
                _route.model=model
                return text
            return _timed('gemini',call)
        if selected != "ollama":
            raise LocalModelError("Bu adapter seçilen sağlayıcı için görüntü desteklemiyor.")
        import base64
        with open(image_path, "rb") as f:
            b64 = base64.b64encode(f.read()).decode()
        return _ollama([{"role": "user", "content": prompt}], system, max_tokens, images=[b64],model=model)
    except requests_state.Cancelled:
        raise
    except Exception as e:
        _record_failure('modules/llm.py:ask_image')
        raise


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
