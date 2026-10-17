"""Jarvis araçları için ortak hata sınıflandırma ve recovery politikası.

Ham sağlayıcı hataları farklı modüllerde farklı biçimde yorumlanmasın. Bu modül yalnız
hata sınıfı, güvenli tanı özeti, cooldown ve bir sonraki yöntem türünü belirler; kendisi
harici işlem yapmaz.
"""
from __future__ import annotations
import re

CANCELLED = 'cancelled'
AUTH = 'auth'
RATE_LIMIT = 'rate_limit'
DNS = 'dns'
TIMEOUT = 'timeout'
NETWORK = 'network'
PROVIDER_DOWN = 'provider_down'
PERMISSION = 'permission'
SOURCE_INVALID = 'source_invalid'
ENVIRONMENT = 'environment'
VALIDATION = 'validation'
USER_INPUT = 'user_input_required'
UNKNOWN = 'unknown'


def status_code(exc: BaseException) -> int | None:
    code = getattr(exc, 'code', None)
    if not isinstance(code, int):
        code = getattr(exc, 'status_code', None)
    if not isinstance(code, int):
        code = getattr(getattr(exc, 'response', None), 'status_code', None)
    return code if type(code) is int and 100 <= code <= 599 else None


def classify(exc: BaseException) -> str:
    name = type(exc).__name__.casefold()
    text = (type(exc).__name__ + ' ' + str(exc)).casefold()
    code = status_code(exc)
    if name == 'cancelled':
        return CANCELLED
    if code == 429 or re.search(r'\b429\b|resource_exhausted|quota|rate[ _-]?limit|token sınır', text, re.I):
        return RATE_LIMIT
    if code in (401, 403) or re.search(r'api[_ -]?key|unauthenticated|invalid[_ -]?grant|revoked|kimlik|yetkisiz', text, re.I):
        return AUTH
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


def recovery_action(category: str, *, context: str = '') -> str:
    """Return strategy name only; caller decides which safe adapter implements it."""
    if category in {RATE_LIMIT, PROVIDER_DOWN}:
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
    if category == VALIDATION:
        return 'fix_input_or_code'
    if category == CANCELLED:
        return 'stop'
    return 'stop'


def cooldown_seconds(provider: str, exc: BaseException) -> int:
    category = classify(exc)
    if category == AUTH:
        return 1800
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
    if category == RATE_LIMIT:
        return 'quota'
    return 'other'


def network_unavailable(exc: BaseException) -> bool:
    return classify(exc) in {DNS, NETWORK, TIMEOUT}


def snapshot(exc: BaseException, *, provider: str = '', context: str = '') -> dict:
    category = classify(exc)
    return {
        'category': category,
        'action': recovery_action(category, context=context),
        'provider': provider,
        'error_type': type(exc).__name__,
        'status': status_code(exc),
    }


def failure_detail(provider: str, exc: BaseException) -> str:
    category = classify(exc)
    reason = {
        AUTH: 'kimlik/erişim reddedildi',
        RATE_LIMIT: 'kota veya hız sınırı',
        DNS: 'DNS çözümlemesi başarısız',
        TIMEOUT: 'zaman aşımı',
        NETWORK: 'bağlantı kurulamadı veya kesildi',
        PROVIDER_DOWN: 'servis geçici olarak kullanılamıyor',
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
        DNS: 'DNS üzerinden sunucuya ulaşamadı',
        TIMEOUT: 'zaman aşımına uğradı',
        NETWORK: 'ağ bağlantısı kurulamadı',
        PROVIDER_DOWN: 'servis geçici olarak yanıt vermedi',
    }.get(classify(exc), 'yanıt vermedi')


def explain(exc: BaseException) -> str:
    """User-facing diagnosis without leaking raw provider internals unnecessarily."""
    name = type(exc).__name__
    message = str(exc)
    if name in ('LocalModelError', 'CloudError') and message:
        return message
    category = classify(exc)
    if category == RATE_LIMIT:
        return 'Yapay zekâ kullanım sınırı doldu; Jarvis uygun başka sağlayıcı veya modelsiz yolu denemeli.'
    if category == AUTH:
        return 'Bağlantı veya hesap izni geçersiz. İlgili entegrasyonun bağlantısını kontrol et.'
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
