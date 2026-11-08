"""Jarvis araçları için ortak hata sınıflandırma ve recovery politikası.

Ham sağlayıcı hataları farklı modüllerde farklı biçimde yorumlanmasın. Bu modül yalnız
hata sınıfı, güvenli tanı özeti, cooldown ve bir sonraki yöntem türünü belirler; kendisi
harici işlem yapmaz.
"""
from __future__ import annotations
import random
import re
import time

CANCELLED = 'cancelled'
AUTH = 'auth'
RATE_LIMIT = 'rate_limit'            # geçici: dakikalık istek/token sınırı, kısa süre sonra açılır
QUOTA_EXHAUSTED = 'quota_exhausted'  # kalıcı: günlük/hesap kotası bitti, beklemek bugün açmaz
LOCAL_MODEL = 'local_model'          # Ollama kurulu/çalışır değil ya da istenen model indirilmemiş
DNS = 'dns'
TIMEOUT = 'timeout'
LOCAL_TIMEOUT = 'local_timeout'      # kendi süre bütçemiz doldu; sağlayıcı susmadı, cezalandırılmaz
NETWORK = 'network'
PROVIDER_DOWN = 'provider_down'
PROVIDER_EXHAUSTED = 'provider_exhausted'
PERMISSION = 'permission'
SOURCE_INVALID = 'source_invalid'
ENVIRONMENT = 'environment'
VALIDATION = 'validation'
USER_INPUT = 'user_input_required'
UNKNOWN = 'unknown'

_PROVIDER_REASON_CODES = {
    RATE_LIMIT: 'PROVIDER_RATE_LIMIT',
    QUOTA_EXHAUSTED: 'PROVIDER_QUOTA_EXHAUSTED',
    LOCAL_MODEL: 'PROVIDER_LOCAL_MODEL',
    AUTH: 'PROVIDER_AUTH',
    DNS: 'PROVIDER_DNS',
    NETWORK: 'PROVIDER_NETWORK',
    TIMEOUT: 'PROVIDER_TIMEOUT',
    LOCAL_TIMEOUT: 'LOCAL_DEADLINE_EXCEEDED',
    PROVIDER_DOWN: 'PROVIDER_DOWN',
    ENVIRONMENT: 'PROVIDER_ENVIRONMENT',
    PROVIDER_EXHAUSTED: 'PROVIDER_POOL_EXHAUSTED',
}

_PROVIDER_RECOVERY_CLASSES = {
    RATE_LIMIT: 'fallback_possible',
    QUOTA_EXHAUSTED: 'fallback_possible',
    LOCAL_MODEL: 'user_action_required',
    AUTH: 'fallback_possible',
    DNS: 'retryable',
    NETWORK: 'retryable',
    TIMEOUT: 'retryable',
    LOCAL_TIMEOUT: 'fail_closed',    # bütçe dolmuşken yeni deneme aynı duvara döner: otomatik retry yok
    PROVIDER_DOWN: 'fallback_possible',
    ENVIRONMENT: 'user_action_required',
    PROVIDER_EXHAUSTED: 'fail_closed',
}


class ProviderExhaustedError(RuntimeError):
    """Safe aggregate failure after the bounded free-provider pool cannot answer."""

    def __init__(self, message: str, *, reason_code: str = 'PROVIDER_POOL_EXHAUSTED',
                 recovery_class: str = 'fail_closed'):
        super().__init__(message)
        self.reason_code = reason_code
        self.recovery_class = recovery_class


def status_code(exc: BaseException) -> int | None:
    code = getattr(exc, 'code', None)
    if not isinstance(code, int):
        code = getattr(exc, 'status_code', None)
    if not isinstance(code, int):
        code = getattr(getattr(exc, 'response', None), 'status_code', None)
    return code if type(code) is int and 100 <= code <= 599 else None


# Yalnız açık günlük/hesap kotası ifadesi kalıcı sayılır. Gemini her 429'da "exceeded your current quota"
# yazdığı için bu cümle ve çıplak 429 kalıcı kota kanıtı değildir.
_QUOTA_EXHAUSTED_RE = re.compile(r'per ?day|daily|günlük|insufficient_quota|\btpd\b|\brpd\b', re.I)
_LOCAL_MODEL_TYPES = {'localmodelerror', 'imagecapabilityerror'}


def quota_exhausted_text(text) -> bool:
    """429 gövdesi günlük/hesap kotasının bittiğini açıkça söylüyor mu (kalıcı, beklemek bugün açmaz)?"""
    return bool(_QUOTA_EXHAUSTED_RE.search(str(text or '')))


def classify(exc: BaseException) -> str:
    if isinstance(exc, ProviderExhaustedError):
        return PROVIDER_EXHAUSTED
    name = type(exc).__name__.casefold()
    text = (type(exc).__name__ + ' ' + str(exc)).casefold()
    code = status_code(exc)
    if name == 'cancelled':
        return CANCELLED
    if getattr(exc, 'local_deadline', False) is True:
        # requests_state.LocalDeadline: TimeoutError alt sınıfı olduğu için aşağıdaki timeout
        # dalına düşer ve sağlayıcı gibi 60 sn cooldown yerdi; açık işaret onu kendi sınıfına alır.
        return LOCAL_TIMEOUT
    if code == 429 or re.search(r'\b429\b|resource_exhausted|quota|rate[ _-]?limit|token sınır', text, re.I):
        return QUOTA_EXHAUSTED if _QUOTA_EXHAUSTED_RE.search(text) else RATE_LIMIT
    if code in (401, 403) or re.search(r'api[_ -]?key|unauthenticated|invalid[_ -]?grant|revoked|kimlik|yetkisiz'
                                       r'|anahtar\w*\s+(?:geçersiz|yok)', text, re.I):
        return AUTH
    if name in _LOCAL_MODEL_TYPES and any(server in text for server in ('ollama', 'lm studio', 'llama.cpp')):
        return LOCAL_MODEL
    if name in {'servernotfounderror', 'gaierror'} or any(part in text for part in (
        'unable to find the server', 'name or service not known', 'temporary failure in name resolution',
        'getaddrinfo failed', 'name resolution', 'dns',
    )):
        return DNS
    if name in {'timeout', 'timeouterror', 'readtimeout', 'connecttimeout', 'connecttimeouterror', 'readtimeouterror'} or 'timed out' in text or 'timeout' in text:
        return TIMEOUT
    if name in {'connectionerror', 'connecterror', 'connectionreseterror', 'connectionrefusederror', 'connectionabortederror'} or any(part in text for part in (
        'network is unreachable', 'connection refused', 'connection reset', 'connection aborted', 'connection failed',
    )):
        return NETWORK
    if code in (500, 502, 503, 504) or re.search(r'overloaded|service unavailable|provider unavailable|server unavailable', text):
        return PROVIDER_DOWN
    if isinstance(exc, PermissionError):
        return PERMISSION
    if re.search(r'tekil haber|kaynak.*(?:geçersiz|yanıtlamıyor|bulunamadı)|source.*(?:invalid|missing)|haber dizini', text):
        return SOURCE_INVALID
    if isinstance(exc, (FileNotFoundError, ModuleNotFoundError, ImportError)) or re.search(r'paket.*eksik|kurulu değil|runtime.*eksik|executable.*not found', text):
        return ENVIRONMENT
    if re.search(r'kullanıcıdan|kullanici.*gerekli|hedef kişi|dosya seçimi|onay gerekli', text):
        return USER_INPUT
    if isinstance(exc, (ValueError, TypeError, AssertionError)):
        return VALIDATION
    return UNKNOWN


def reason_code(exc_or_category) -> str | None:
    """Stable machine-readable code for provider/runtime failures only."""
    if isinstance(exc_or_category, BaseException):
        explicit = getattr(exc_or_category, 'reason_code', None)
        if isinstance(explicit, str) and explicit:
            return explicit
        category = classify(exc_or_category)
    else:
        category = exc_or_category
    return _PROVIDER_REASON_CODES.get(category)


def recovery_class(exc_or_category) -> str | None:
    """Coarse recovery class; it never executes a retry or fallback itself."""
    if isinstance(exc_or_category, BaseException):
        explicit = getattr(exc_or_category, 'recovery_class', None)
        if isinstance(explicit, str) and explicit:
            return explicit
        category = classify(exc_or_category)
    else:
        category = exc_or_category
    return _PROVIDER_RECOVERY_CLASSES.get(category)


def structured_outcome(exc: BaseException) -> dict | None:
    """Return safe provider failure metadata without changing WorkerResult/GoalState schemas."""
    code = reason_code(exc)
    recovery = recovery_class(exc)
    if not code or not recovery:
        return None
    return {'reason_code': code, 'recovery_class': recovery}


def recovery_action(category: str, *, context: str = '') -> str:
    """Return strategy name only; caller decides which safe adapter implements it."""
    if category in {RATE_LIMIT, QUOTA_EXHAUSTED, LOCAL_MODEL, PROVIDER_DOWN}:
        return 'alternate_provider'
    if category in {DNS, NETWORK, TIMEOUT}:
        return 'alternate_path'
    if category == SOURCE_INVALID:
        return 'alternate_source'
    if category == AUTH:
        return 'alternate_provider' if context in {'model', 'planner'} else 'request_connection'
    if category in {PERMISSION, USER_INPUT}:
        return 'request_user_input'
    if category == ENVIRONMENT:
        return 'alternate_environment'
    if category == PROVIDER_EXHAUSTED:
        return 'stop'
    if category == VALIDATION:
        return 'fix_input_or_code'
    if category == CANCELLED:
        return 'stop'
    if category == LOCAL_TIMEOUT:
        return 'stop'    # yeni aday/sağlayıcı aynı bitmiş bütçeye döner; kararı çağıran verir
    return 'stop'


def cooldown_seconds(provider: str, exc: BaseException) -> int:
    category = classify(exc)
    if category == LOCAL_TIMEOUT:
        return 0    # kendi süremiz doldu; sağlıklı sağlayıcı ceza almaz
    if category == AUTH:
        return 1800
    if category == QUOTA_EXHAUSTED:
        return 3600
    if category == RATE_LIMIT:
        return 300
    if provider == 'ollama':
        return 30
    if category in {DNS, NETWORK, TIMEOUT, PROVIDER_DOWN, UNKNOWN}:
        return 60
    return 60


def legacy_kind(exc: BaseException) -> str:
    category = classify(exc)
    if category == AUTH:
        return 'key'
    if category in {RATE_LIMIT, QUOTA_EXHAUSTED}:
        return 'quota'
    return 'other'


def network_unavailable(exc: BaseException) -> bool:
    return classify(exc) in {DNS, NETWORK, TIMEOUT}


def snapshot(exc: BaseException, *, provider: str = '', context: str = '') -> dict:
    category = classify(exc)
    row = {
        'category': category,
        'action': recovery_action(category, context=context),
        'provider': provider,
        'error_type': type(exc).__name__,
        'status': status_code(exc),
    }
    structured = structured_outcome(exc)
    if structured:
        row.update(structured)
    return row


def failure_detail(provider: str, exc: BaseException) -> str:
    category = classify(exc)
    reason = {
        AUTH: 'kimlik/erişim reddedildi',
        RATE_LIMIT: 'geçici hız sınırı',
        QUOTA_EXHAUSTED: 'günlük kota doldu',
        LOCAL_MODEL: 'yerel model yok',
        DNS: 'DNS çözümlemesi başarısız',
        TIMEOUT: 'zaman aşımı',
        LOCAL_TIMEOUT: 'bekleme süremiz doldu (sağlayıcı hatası değil)',
        NETWORK: 'bağlantı kurulamadı veya kesildi',
        PROVIDER_DOWN: 'servis geçici olarak kullanılamıyor',
        PROVIDER_EXHAUSTED: 'uygun sağlayıcı kalmadı',
        PERMISSION: 'izin gerekli',
        ENVIRONMENT: 'yerel çalışma ortamı eksik',
        VALIDATION: 'çıktı veya girdi doğrulanamadı',
    }.get(category, 'çağrı başarısız')
    code = status_code(exc)
    return provider + ': ' + reason + ' (' + type(exc).__name__ + (f', HTTP {code}' if code else '') + ')'


def short_text(exc: BaseException) -> str:
    return {
        AUTH: 'anahtarı veya izni geçersiz',
        RATE_LIMIT: 'istek/token sınırına takıldı',
        QUOTA_EXHAUSTED: 'günlük kotası doldu',
        LOCAL_MODEL: 'yerel model kullanılamadı',
        DNS: 'DNS üzerinden sunucuya ulaşamadı',
        TIMEOUT: 'zaman aşımına uğradı',
        LOCAL_TIMEOUT: 'kendi bekleme süresi doldu (sağlayıcı susmadı)',
        NETWORK: 'ağ bağlantısı kurulamadı',
        PROVIDER_DOWN: 'servis geçici olarak yanıt vermedi',
        PROVIDER_EXHAUSTED: 'uygun ücretsiz sağlayıcı kalmadı',
        ENVIRONMENT: 'yerel çalışma ortamı eksik',
    }.get(classify(exc), 'yanıt vermedi')


# Sağlayıcı/ağ/model hataları: kullanıcıya ham metin yerine sınıflandırılmış açıklama gider.
PROVIDER_CATEGORIES = frozenset({RATE_LIMIT, QUOTA_EXHAUSTED, LOCAL_MODEL, AUTH, DNS, NETWORK, TIMEOUT,
                                 PROVIDER_DOWN, ENVIRONMENT, PROVIDER_EXHAUSTED})


def user_message(exc: BaseException) -> str:
    """Sağlayıcı/ağ hatasında güvenli açıklama, diğer hatalarda kendi özgül mesajı (ör. 'Not metni boş')."""
    if classify(exc) in PROVIDER_CATEGORIES:
        return explain(exc)
    return str(exc).strip() or explain(exc)


# ------------------------------------------------------------------ sınırlı yeniden deneme
MAX_RETRIES = 3          # aynı hedefe en fazla deneme sayısı (ilk deneme dahil)
BACKOFF_BASE = 1.0       # ilk bekleme (sn); her denemede iki katına çıkar
BACKOFF_CAP = 8.0        # tek beklemenin üst sınırı (sn)


def is_transient(exc_or_category) -> bool:
    """Aynı hedefte kısa beklemeyle yeniden denemeye değer mi? 429/kota/kimlik/yerel model hayır."""
    category = classify(exc_or_category) if isinstance(exc_or_category, BaseException) else exc_or_category
    return category in {DNS, NETWORK, TIMEOUT, PROVIDER_DOWN}


def backoff_delay(attempt: int, *, base: float = BACKOFF_BASE, cap: float = BACKOFF_CAP, rand=None) -> float:
    """attempt. başarısız denemeden sonra beklenecek saniye: base*2^(attempt-1), üstten cap ile sınırlı.

    Yarım jitter (%50-%100) aynı anda düşen istekler aynı saniyede yeniden vurmasın diye eklenir.
    """
    attempt = max(1, int(attempt))
    delay = min(cap, base * (2 ** (attempt - 1)))
    return round(delay * (0.5 + 0.5 * (rand or random.random)()), 3)


def backoff_sleep(attempt: int, *, check=None, sleep=None, **kwargs) -> float:
    """backoff_delay kadar bekler; check verilirse (ör. requests_state.check) bekleme dilimlerle bölünür
    ve iptal/zaman aşımı beklemenin ortasında da yakalanır."""
    sleep = sleep or time.sleep
    delay = backoff_delay(attempt, **kwargs)
    left = delay
    while left > 0:
        if check is not None:
            check()
        step = min(0.25, left)
        sleep(step)
        left -= step
    if check is not None:
        check()
    return delay


def explain(exc: BaseException) -> str:
    """User-facing diagnosis without leaking raw provider internals unnecessarily."""
    if isinstance(exc, ProviderExhaustedError):
        return str(exc)
    category = classify(exc)
    if category in (DNS, NETWORK):
        from modules import ollama_hint
        offline = ollama_hint.offline_text(exc)
        if offline:
            return offline
    if category == RATE_LIMIT:
        return ('Yapay zekâ geçici kullanım sınırına takıldı (dakikalık istek sınırı; günlük kota bitmedi). '
                'Bir dakika kadar bekleyip tekrar dene.')
    if category == QUOTA_EXHAUSTED:
        return ('Yapay zekânın günlük kotası doldu; beklemek bugün açmaz. Kota yarın yenilenir; '
                'şimdi devam etmek için Bağlantılar sayfasından kendi Groq anahtarını ekleyebilir ya da yerel modeli (Ollama) kullanabilirsin.')
    if category == LOCAL_MODEL:
        from modules import ollama_hint
        model = re.search(r'“([\w.:/-]{1,80})” modeli yok', str(exc))
        if model:
            return f"Yerel modelde “{model.group(1)}” indirilmemiş. Terminalde `ollama pull {model.group(1)}` yaz."
        if type(exc).__name__ == 'ImageCapabilityError':
            return ollama_hint.IMAGE
        return 'Yerel model (Ollama) kurulu değil ya da çalışmıyor: ' + ollama_hint.INSTALL + '.'
    if category == AUTH:
        return ('Kimlik doğrulama reddedildi: API anahtarı veya hesap izni geçersiz. '
                'Bağlantılar sayfasından anahtarı ya da ilgili hesabın bağlantısını kontrol et.')
    if category == DNS:
        return 'Sunucu adı DNS üzerinden çözümlenemedi. Hesap izni korunur; ağ düzeldiğinde yeniden denenebilir.'
    if category == TIMEOUT:
        return 'Yanıt zaman aşımına uğradı. Jarvis uygun başka yol varsa ona geçmeli.'
    if category == NETWORK:
        return 'Ağ bağlantısı kurulamadı veya kesildi. Jarvis çevrimdışı/alternatif yolu varsa kullanmalı.'
    if category == PROVIDER_DOWN:
        return 'Servis geçici olarak kullanılamıyor; uygun alternatif sağlayıcı denenmeli.'
    if category == PERMISSION:
        return 'Bu işlem için kullanıcı izni gerekli.'
    if category == ENVIRONMENT:
        return 'Bu işlem için gereken yerel çalışma bileşeni eksik.'
    if category == SOURCE_INVALID:
        return 'Seçilen kaynak doğrulanamadı; başka gerçek kaynak denenmeli.'
    if category == VALIDATION:
        return 'İşlem sonucu doğrulanamadı; tamamlandı sayılmamalı.'
    return 'Bu işlem sırasında sınıflandırılmamış bir hata oluştu; tanı kaydına bakılmalı.'
