"""Tüm modüllerin paylaştığı LLM istemcisi (Google Gemini)."""
from modules.diagnostics import record_failure as _record_failure
import time
import logging
import threading
from urllib.parse import urlparse

log = logging.getLogger("jarvis.llm")
from contextvars import ContextVar
from modules import requests_state

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
from modules import privacy


class LocalModelError(RuntimeError):
    """Ollama'ya ulaşılamadı ya da model yok."""

class ImageCapabilityError(LocalModelError):
    """Ollama modeli çalışıyor fakat görüntü girdisini desteklemiyor."""


def _cfg() -> dict:
    s = load_settings()
    configured = s.get("provider") or "gemini"
    if configured not in {"auto", "openrouter", "gemini", "groq", "ollama", "openai", "anthropic"}:
        configured = "gemini"
    return {"provider": configured,
            "url": (s.get("ollama_url") or "http://127.0.0.1:11434").rstrip("/"),
            "model": s.get("ollama_model") or "llama3.2"}


GROQ_MODELS = ["openai/gpt-oss-120b", "openai/gpt-oss-20b", "qwen/qwen3.8-27b"]
_DEPRECATED_GROQ = {"llama-3.3-70b-versatile", "llama-3.1-8b-instant", "qwen/qwen3.6-27b"}
_GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"


def groq_model() -> str:
    """Etkin Groq modeli. Eski/deprecated ücretsiz modelleri güvenli varsayılana taşır."""
    model = (load_settings().get("groq_model") or "").strip()
    if not model or model in _DEPRECATED_GROQ:
        return GROQ_MODELS[0]
    return model


def provider() -> str:
    """Şu an kullanılacak sağlayıcı: gemini | groq | ollama. Yerel gizlilik modu daima Ollama'dır."""
    return "ollama" if privacy.mode() == "yerel" else _cfg()["provider"]


def gemini_aux_allowed() -> bool:
    """In automatic mode, auxiliary Gemini calls share the free-account policy."""
    if provider() != 'auto': return True
    from modules import smart_router
    return bool(smart_router.settings(current_user()).get('cloud_free_confirmed'))


_ollama_tags_lock = threading.Lock()
_ollama_tags_cache = {}


def ollama_models(force=False) -> list[str]:
    url = _cfg()['url']
    with _ollama_tags_lock:
        cached = _ollama_tags_cache.get(url)
        # Kurulu olmayan (boş) sonuç daha uzun tutulur: kapalı yerel porta bağlanmak Windows'ta saniyeler sürebilir.
        if not force and cached and time.monotonic() - cached[0] < (3 if cached[1] else 20):
            return list(cached[1])
        try:
            host = (urlparse(url).hostname or '').lower()
            connect = 0.4 if host in ('127.0.0.1', 'localhost', '::1') else 3   # yerel Ollama yoksa açılışı bekletme
            r = requests.get(url + '/api/tags', timeout=(connect, 3))
            r.raise_for_status()
            rows = sorted(m['name'] for m in r.json().get('models', []) if isinstance(m.get('name'), str))
        except (requests.RequestException, ValueError, TypeError, AttributeError):
            rows = []
        if len(_ollama_tags_cache) >= 8:
            _ollama_tags_cache.clear()
        _ollama_tags_cache[url] = (time.monotonic(), rows)
        return list(rows)


def model_check(force=False):
    from modules import model_health
    if privacy.mode() in ("gizli", "yerel"):
        return {"state":"private", "message":"Gizli/yerel modda bulut model kontrolü kapalı."}
    if not gemini_aux_allowed():
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
            "ollama_url": c["url"], "ollama_model": c["model"], "ollama_up": bool(om), "ollama_models": om}


def set_provider(name: str, model: str | None = None, url: str | None = None) -> None:
    if name not in ("auto", "openrouter", "gemini", "ollama", "groq", "openai", "anthropic"):
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
    ch = {"provider": name, "ai_mode": name}
    if model and name == "groq":
        ch["groq_model"] = model.strip()
    elif model and name == "ollama":
        ch["ollama_model"] = model.strip()
    if url:
        ch["ollama_url"] = url.strip()
    save_settings(**ch)


def _ollama(messages: list[dict], system: str, max_tokens: int, images: list[str] | None = None,
            model: str | None = None) -> str:
    c = _cfg()
    model = model or c["model"]
    msgs = ([{"role": "system", "content": system}] if system else []) + messages
    if images:
        msgs[-1] = {**msgs[-1], "images": images}
    try:
        r = requests.post(c["url"] + "/api/chat", timeout=(5, 45),
                          json={"model": model, "messages": msgs, "stream": False,
                                "options": {"num_predict": max_tokens}})
    except requests.RequestException as e:
        raise LocalModelError("Yerel model (Ollama) çalışmıyor. ollama.com'dan kurup `ollama serve` ile başlat.") from e
    if r.status_code == 404:
        raise LocalModelError(f"Ollama'da “{model}” modeli yok. Terminalde `ollama pull {model}` yaz.")
    if r.status_code >= 400:
        detail = str((r.json() if r.content else {}).get('error','')).casefold()
        if any(word in detail for word in ('image', 'vision', 'multimodal', 'does not support')):
            raise ImageCapabilityError('Ollama modeli görüntü girdisini desteklemiyor.')
        raise LocalModelError(f"Ollama hata verdi ({r.status_code}).")
    _route.model = model
    return (r.json().get("message") or {}).get("content", "")


OLLAMA_BIG_MODEL = "qwen2.5:7b"


def ollama_model_for(prompt: str) -> str:
    """Kod ve analizde yüklüyse büyük yerel model (qwen2.5:7b), sohbette ayarlı küçük model (llama3.2 = 3b)."""
    base = _cfg()["model"]
    big = (load_settings().get("ollama_big_model") or OLLAMA_BIG_MODEL).strip()
    if not big or big == base:
        return base
    from modules import smart_router
    if smart_router.task_type(prompt) in ("code", "analysis") and big in ollama_models():
        return big
    return base


def _ollama_task(messages: list[dict], system: str, max_tokens: int, prompt: str) -> str:
    """Göreve uygun yerel modeli dener; büyük model çalışmazsa (bellek, bozuk model) küçük modele düşer."""
    base = _cfg()["model"]
    model = ollama_model_for(prompt)
    if model != base:
        try:
            return _ollama(messages, system, max_tokens, model=model)
        except ImageCapabilityError:
            raise
        except LocalModelError:
            note_route(f"{model} yanıt vermedi, {base} kullanılıyor", False)
    return _ollama(messages, system, max_tokens, model=base)




class CloudError(RuntimeError):
    """Bulut sağlayıcısına ulaşılamadı / anahtar geçersiz."""



def _groq(messages: list[dict], system: str, max_tokens: int) -> str:
    """Groq OpenAI-uyumlu Chat Completions API."""
    key = user_groq_key(current_user())
    if not key:
        raise CloudError("Bu kullanıcının Groq API anahtarı yok. Bağlantılar sayfasından ekle.")
    msgs = ([{"role": "system", "content": system}] if system else []) + [dict(m) for m in messages]
    headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
    body = {"model": groq_model(), "messages": msgs, "max_tokens": max_tokens, "temperature": 0.2}
    last = ""
    for attempt in range(1, 3):
        requests_state.check()
        try:
            r = requests.post(_GROQ_URL, headers=headers, json=body, timeout=(5, 30))
        except requests.RequestException as e:
            last = type(e).__name__; time.sleep(attempt); continue
        if r.status_code == 200:
            try:
                text = r.json()["choices"][0]["message"]["content"] or ""
                _route.model = groq_model()
                return text
            except (KeyError, IndexError, TypeError, ValueError) as e:
                raise CloudError("Groq beklenmeyen bir yanıt döndürdü.") from e
        try:
            msg = (r.json().get("error") or {}).get("message", "")
        except ValueError:
            msg = ""
        if r.status_code in (401, 403):
            raise CloudError("Groq API anahtarı geçersiz ya da yetkisiz.")
        if r.status_code == 404:
            raise CloudError(f"Groq modeli bu hesapta kullanılamıyor/bulunamadı: {groq_model()}. Ayarlar > Groq modelinden güncel bir model seç.")
        last = f"{r.status_code} {msg[:100]}"
        if r.status_code in (429, 500, 502, 503, 504):
            time.sleep(attempt); continue
        break
    raise CloudError("Groq yanıt vermedi (" + last + ")")


def _need_cloud(prompt: str) -> str:
    """Buluta gitmeden önce: yerel modda engelle, değilse hassas bilgiyi maskele."""
    if privacy.mode() == "yerel":
        raise LocalModelError("Yalnızca yerel mod açık ama yerel model yanıt vermedi.")
    return privacy.redact(prompt)


def embed(texts: list[str]) -> list[list[float]]:
    """Metin vektörleri (anlamsal arama). Yerel modda Ollama, aksi halde Gemini. Başarısızsa ValueError."""
    c = _cfg()
    out: list[list[float]] = []
    if provider() == "ollama":
        model = load_settings().get("ollama_embed_model") or "nomic-embed-text"
        try:
            from modules import ollama_embed
            out = ollama_embed.run(texts, c["url"], model)
        except (requests.RequestException, KeyError, ValueError, AttributeError) as e:
            raise ValueError("Yerel gömme modeli yok (`ollama pull nomic-embed-text`).") from e
        return out
    if not gemini_aux_allowed():
        raise ValueError('Smart Router: Gemini gömme için ücretsiz hesap doğrulaması gerekli.')
    client = _cli()
    if client is None:
        raise ValueError("Bu kullanıcının Gemini anahtarı yok.")
    try:
        for i in range(0, len(texts), 50):
            part = [privacy.redact(t) for t in texts[i:i + 50]]
            resp = client.models.embed_content(model="gemini-embedding-001", contents=part)
            out += [list(e.values) for e in resp.embeddings]
    except Exception as e:
        _record_failure('modules/llm.py:embed')
        raise ValueError(f"Gömme alınamadı: {e}") from e
    return out


_SWITCH_CODES = {404, 429, 500, 502, 503, 504}   # bunlarda bekleme/yedek modele geçiş denenir
_MODELS = [MODEL, *[m for m in FALLBACK_MODELS if m != MODEL]]
_MAX_TRIES = 3        # aynı modele en fazla kaç deneme (araya 1 ve 2 sn bekleme)
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
    return "PerDay" in str(e)


_fallback_lock = threading.Lock()
_fallback_states = {}


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


def _with_models(call):
    """call(model) fonksiyonunu çalıştırır: geçici hatada bekleyip tekrar dener, olmazsa yedek modele geçer."""
    owner=current_user()
    models=model_names(owner)
    identity=(owner,tuple(models))
    with _fallback_lock:
        active, switched_at=_fallback_states.get(identity,(0,0))
    if active and time.time() - switched_at > 600:
        active = 0                       # yedekte 10 dk geçti: ana (hızlı) modele dön
    last: Exception | None = None
    for step in range(len(models)):
        idx = (active + step) % len(models)
        model = models[idx]
        for attempt in range(1, _MAX_TRIES + 1):
            requests_state.check()
            try:
                result = call(model)
                requests_state.check()
                _route.model = model
                if idx != active:
                    print(f"(Yedek model kullanılıyor: {model})")
                    with _fallback_lock:
                        _fallback_states[identity] = (idx, time.time())
                return result
            except (errors.ServerError, errors.ClientError) as e:
                last = e
                code = getattr(e, "code", None)
                if code not in _SWITCH_CODES:
                    raise
                if code == 404 or _daily_quota(e) or attempt == _MAX_TRIES:
                    break   # bu modelde ısrar etme, sıradakine geç
                if code == 429 and step < len(models) - 1:
                    break   # kullanım sınırı: beklemek yerine hemen yedek modele geç (yedeğin sınırı ayrıdır)
                wait = 2 ** (attempt - 1)   # 1, 2 saniye
                print(f"(Gemini {code} verdi, {wait} sn sonra tekrar deneniyor... [{attempt}/{_MAX_TRIES - 1}])")
                time.sleep(wait)
    if last is None:
        raise RuntimeError("Yanıt verecek model yapılandırılmamış.")
    raise last


# Arayüzdeki AI Modelleri kartı için: gerçek isteklerin son cevap süresi (ek/deneme isteği atılmaz, kota harcamaz).
LAST_SEC: dict = {}


_LABELS = {"gemini": "Gemini", "groq": "Groq", "ollama": "Ollama (yerel)", "openrouter": "OpenRouter",
           "openai": "OpenAI", "anthropic": "Claude"}
_route = threading.local()   # bu iş parçacığındaki isteğin model izi; yalnız sağlayıcı/model adı, metin yok


def provider_label(name: str) -> str:
    return _LABELS.get(name, name)


def note_route(text: str, ok: bool) -> None:
    notes = getattr(_route, "notes", None)
    if notes is None:
        notes = _route.notes = []
    notes.append((text, ok))
    del notes[:-8]


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
    out = fn()
    requests_state.check()
    LAST_SEC[name] = round(time.time() - t0, 1)
    model = getattr(_route, "model", None)
    note_route("Cevap: " + provider_label(name) + (f" · {model}" if model else ""), True)
    return out


def _send(prompt: str, system: str, max_tokens: int, history, selected=None, strict=False) -> str:
    selected=selected or provider()
    if selected == 'auto':
        from modules import smart_router
        return smart_router.run(current_user(), prompt + '\n' + system,
            lambda name: _send(prompt, system, max_tokens, history, name, True))
    if selected == 'openrouter':
        from modules import smart_router
        return _timed('openrouter',lambda:smart_router.openrouter(current_user(),
            _ohist_msgs(history)+[{'role':'user','content':prompt}],system,max_tokens))
    if selected != 'ollama' and history:
        history = [types.Content(role=h.role,parts=[types.Part(text=privacy.redact(p.text)) for p in h.parts if getattr(p,'text',None)]) for h in history]
    if selected in ('openai','anthropic'):
        from modules import paid_providers
        return _timed(selected,lambda:paid_providers.generate(current_user(),selected,
                      _ohist_msgs(history)+[{'role':'user','content':prompt}],system,max_tokens))
    if selected == "groq":
        try:
            return _timed("groq", lambda: _groq(_ohist_msgs(history) + [{"role": "user", "content": privacy.redact(prompt)}],
                         privacy.redact(system), max_tokens))
        except CloudError as e:
            if strict or _cli() is None:
                raise LocalModelError(str(e)) from e
            print(f"({e} Gemini'ye geçiliyor)")
            note_route("Groq yanıt vermedi, Gemini'ye geçildi", False)
    if selected == "ollama":
        try:
            return _timed("ollama", lambda: _ollama_task(_ohist_msgs(history) + [{"role": "user", "content": prompt}], system, max_tokens, prompt))
        except LocalModelError:
            if strict or privacy.mode() == "yerel" or _cli() is None:
                raise                      # buluta düşmek yasak ya da bu kullanıcının Gemini anahtarı yok
            print("(Yerel model yok, Gemini'ye geçiliyor)")
            note_route("Ollama yanıt vermedi, Gemini'ye geçildi", False)
    prompt = _need_cloud(prompt)
    if _cli() is None:
        raise LocalModelError("Bu kullanıcının Gemini anahtarı yok ve seçili sağlayıcı kullanılamadı.")
    system = privacy.redact(system)
    cfg = types.GenerateContentConfig(
        system_instruction=system or None,
        max_output_tokens=max_tokens,
        automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),   # araç çağrısı kullanmıyoruz
    )

    cli = [_cli()]

    def call(model: str) -> str:
        chat_session = cli[0].chats.create(model=model, config=cfg, history=history)
        resp = chat_session.send_message(prompt)
        return resp.text or ""

    try:
        return _timed("gemini", lambda: _with_models(call))
    except (errors.ServerError, errors.ClientError) as e:
        if strict or getattr(e, "code", None) not in _SWITCH_CODES:
            raise
        from modules import smart_router
        note_route("Gemini " + smart_router.failure_text(e), False)
        return _after_gemini(prompt, system, max_tokens, history, e, selected)


def _after_gemini(prompt: str, system: str, max_tokens: int, history, error: Exception, tried: str) -> str:
    """Tüm Gemini modelleri kota/sunucu hatası verdi: aynı kullanıcının Groq'u, sonra yerel Ollama denenir."""
    for name in ("groq", "ollama"):
        if name == tried or (name == "groq" and not user_groq_key(current_user())):
            continue
        requests_state.check()
        try:
            print("(Gemini yanıt vermedi, " + {"groq": "Groq'a", "ollama": "Ollama'ya"}[name] + " geçiliyor)")
            answer = _send(prompt, system, max_tokens, history, name, True)
        except (LocalModelError, CloudError):
            note_route(provider_label(name) + " de yanıt vermedi", False)
            continue
        if isinstance(answer, str) and answer.strip():
            return answer
    raise error


def _ohist_msgs(history) -> list[dict]:
    """Gemini geçmişini (types.Content) Ollama mesajlarına çevirir."""
    out = []
    for h in history or []:
        role = "assistant" if getattr(h, "role", "") == "model" else "user"
        txt = "".join(getattr(p, "text", "") or "" for p in (getattr(h, "parts", None) or []))
        if txt:
            out.append({"role": role, "content": txt})
    return out


def ask(prompt: str, system: str = "", max_tokens: int = 2000) -> str:
    """Tek seferlik soru, geçmişi hatırlamaz (router ve araçlar için)."""
    return _send(prompt, system, max_tokens, None)


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
    return _send(prompt, system, max_tokens, history)


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


def ask_image(image_path: str, prompt: str, system: str = "", max_tokens: int = 2000) -> str:
    if privacy.mode() == 'gizli': return 'Gizli modda görüntü analizi kapalı.'
    if provider() == 'auto':
        from modules import smart_router
        return smart_router.run(current_user(), prompt, lambda name: _ask_image(image_path,prompt,system,max_tokens,name,True),image=True)
    return _ask_image(image_path,prompt,system,max_tokens)


def _ask_image(image_path, prompt, system='', max_tokens=2000, selected=None, strict=False):
    """Send the original image with its detected MIME type and the owner's client."""
    selected=selected or provider()
    if selected == 'openrouter':
        from modules import smart_router
        return smart_router.openrouter(current_user(),[{'role':'user','content':prompt}],system,max_tokens,image_path)
    requests_state.check()
    if privacy.mode() == "gizli":
        return "Gizli modda görüntü analizi kapalı."
    try:
        if selected in ('openai','anthropic'):
            from modules import paid_providers
            return _timed(selected,lambda:paid_providers.generate(current_user(),selected,
                          [{'role':'user','content':prompt}],system,max_tokens,image_path=image_path))
        if selected == "ollama":
            import base64
            with open(image_path, "rb") as f:
                b64 = base64.b64encode(f.read()).decode()
            try:
                return _ollama([{"role": "user", "content": prompt}], system, max_tokens, images=[b64])
            except LocalModelError as e:
                if strict: raise
                if privacy.mode() == "yerel" or _cli() is None:
                    return str(e)
        if privacy.mode() == "yerel":
            return "Yalnızca yerel modda görüntü, yerel görüntü modeline (örn. llava) gider; o da yanıt vermedi."
        if _cli() is None:
            if strict: raise LocalModelError("Görüntü modeli yok.")
            return "Bu kullanıcının görüntü analizi için Gemini anahtarı ya da yerel görüntü modeli gerekli."
        prompt = privacy.redact(prompt)
        system = privacy.redact(system)
        from PIL import Image
        with Image.open(image_path) as image:
            mime = Image.MIME.get(image.format)
        if mime not in {"image/png", "image/jpeg", "image/webp", "image/gif"}:
            raise ValueError("Desteklenmeyen görüntü biçimi.")
        with open(image_path, "rb") as f:
            image_part = types.Part.from_bytes(data=f.read(), mime_type=mime)

        cfg = types.GenerateContentConfig(
            system_instruction=system or None,
            max_output_tokens=max_tokens,
        )

        def call(model: str) -> str:
            resp = _cli().models.generate_content(model=model, contents=[image_part, prompt], config=cfg)
            return resp.text or ""

        return _with_models(call)
    except requests_state.Cancelled:
        raise
    except Exception as e:
        _record_failure('modules/llm.py:ask_image')
        if strict: raise
        return f"Ekran resmi okunurken hata oluştu: {e}"


def transcribe(audio_path: str | None = None, mime: str = "audio/wav", data: bytes | None = None,
               hints: list[str] | None = None) -> str:
    """Kısa bir ses kaydını Türkçe metne çevirir (Gemini). Gizli/yerel modda ses buluta gitmez.
    hints: sık geçen özel kelimeler/adlar (doğru yazılsın diye: "irsaliye", "Nevzat Bey"…)."""
    if privacy.mode() in ("gizli", "yerel"):
        raise RuntimeError("Ses kaydını yazıya çevirmek için ses buluta gitmesi gerekir; bu mod buna izin vermiyor.")
    if not gemini_aux_allowed():
        raise RuntimeError('Smart Router: Gemini ses için ücretsiz hesap doğrulaması gerekli; ücretsiz web STT kullan.')
    if _cli() is None:
        raise RuntimeError("Bu kullanıcının Gemini anahtarı yok; Ayarlar'dan ekle.")
    if data is None:
        with open(audio_path, "rb") as f:
            data = f.read()
    part = types.Part.from_bytes(data=data, mime_type=mime)
    prompt = ("Bu kısa ses kaydı, bir kişinin bilgisayardaki sesli asistanına Türkçe söylediği bir komut ya da soru. "
              "Söyleneni olduğu gibi, düzgün Türkçe yazımla yaz. Başta asistanın adı ya da 'hey' duyulursa onu yazma. "
              "Yalnızca söylenen metni ver: açıklama, tırnak, not ekleme; "
              "cevap verme. Anlaşılır bir konuşma yoksa (gürültü, öksürük, sessizlik) hiçbir şey yazma.")
    if hints:
        prompt += (" Yazım için yardımcı liste (yalnızca bu kelimeler kayıtta AÇIKÇA söylendiyse bu yazımı kullan; "
                   "listeden kelime uydurma, duymadığını yazma): " + ", ".join(hints[:60]) + ".")
    cfg = types.GenerateContentConfig(max_output_tokens=300, temperature=0.0,
                                      automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True))

    def call(model: str) -> str:
        return (_cli().models.generate_content(model=model, contents=[part, prompt], config=cfg).text or "").strip()

    return _with_models(call).strip()


def gemini_client():
    """Return only the current user's client; preserves the existing key isolation."""
    return _cli()


def provider_configuration():
    """Return a copy of the non-secret provider configuration for status consumers."""
    return dict(_cfg())


def test_groq():
    """Explicit connection test; saving a key alone does not imply this call."""
    return _groq([{"role":"user","content":"Sadece 'tamam' yaz."}], "", 20)
