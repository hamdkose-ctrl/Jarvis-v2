"""Tracebacks without exception messages, request data or chained secrets.

Hata nedenleri artık güvenli bir zincirden geçirilerek kaydedilir:

    1. URL sorgu ve fragment bilgileri kırpılır (anahtar taşıyabilirler),
    2. privacy.redact(..., force=True) ile anahtar/e-posta/IBAN/kart/telefon/T.C. maskelenir,
    3. mesaj uzunluk sınırına çekilir,
    4. hata türü ve güvenli durum kodu (HTTP kodu, errno) ayrıca yazılır.

Kritik işlemlerde kullanıcıya gösterilecek anlaşılır açıklama için user_message() kullanılır.
"""
import logging
import re
import sys
import threading
import time
from pathlib import Path

_lock = threading.Lock()
_recent = {}

_MAX_DETAIL = 300          # maskelenmiş nedenin en fazla uzunluğu
_URL = re.compile(r"(?i)\b[a-z][a-z0-9+.\-]*://[^\s'\"<>]+")
# Şemasız sorgu parçaları: 'yol?anahtar=değer' biçimindeki gizli anahtar taşıyan ekler.
_QUERY = re.compile(r"\S*\?[^\s]*=\S*")


def failure_detail() -> str:
    """Safe error summary for startup logs and user-visible diagnostics."""
    kind, error, traceback = sys.exc_info()
    if kind is None:
        return 'Hata bilgisi yok'
    frames = []
    while traceback is not None:
        code = traceback.tb_frame.f_code
        frames.append(f'{Path(code.co_filename).name}:{traceback.tb_lineno}:{code.co_name}')
        traceback = traceback.tb_next
    return kind.__name__ + '; konumlar: ' + ' -> '.join(frames)


def _strip_url_noise(text: str) -> str:
    """URL'lerin sorgu ve fragment bölümlerini kırpar (gizli anahtar taşıyabilirler).

    Hem şemalı adresler (https://…) hem de şemasız 'yol?anahtar=değer' ekleri kırpılır;
    böylece tek başına gelen sırlar da günlüğe düşmez.
    """
    def clean(match: "re.Match") -> str:
        url = match.group(0)
        url = re.sub(r'(://)[^/\s?#]*@', r'\1[erişim gizlendi]@', url)
        cuts = [i for i in (url.find('#'), url.find('?')) if i != -1]
        return url[:min(cuts)] + '[sorgu gizlendi]' if cuts else url
    return _QUERY.sub(clean, _URL.sub(clean, text))


def _safe_status(exc) -> str:
    """Sızdırmayan durum bilgisi: HTTP durum kodu ya da OSError errno."""
    for attr in ('status_code', 'status', 'code'):
        value = getattr(exc, attr, None)
        if isinstance(value, int):
            return f'kod={value}'
    errno = getattr(exc, 'errno', None)
    if isinstance(errno, int):
        return f'errno={errno}'
    return ''


def safe_reason(exc=None) -> str:
    """Maskelenmiş ama işe yarar hata nedeni. Maskeleme yapılamazsa boş döner (sır yazmaktansa sus)."""
    if exc is None:
        exc = sys.exc_info()[1]
    if exc is None:
        return ''
    text = str(exc)
    if not text.strip():
        return ''
    text = _strip_url_noise(text)
    try:
        # Döngüsel içe aktarmayı önlemek için burada; privacy zaten record_failure'ı içe aktarıyor.
        from modules import privacy
        text = privacy.redact(text, force=True)
    except (ImportError, AttributeError, TypeError, ValueError):
        # Maskeleme yapılamazsa nedeni hiç yazma: ham mesaj sızdırmaktansa sus.
        return ''
    text = re.sub(r"\s+", " ", text).strip()
    return text[:_MAX_DETAIL] + ('…' if len(text) > _MAX_DETAIL else '')


def record_failure(context: str) -> None:
    """Record each failure site/type, rate limited during repeated device retries.

    Only static code context, exception type, traceback locations and a masked,
    URL-stripped reason are emitted. Original exception messages, causes, local
    variables and provider URLs are never written verbatim.
    """
    kind, error, traceback = sys.exc_info()
    if kind is None:
        return
    site = (traceback.tb_frame.f_code.co_filename, traceback.tb_lineno) if traceback else ('', 0)
    key = (context, kind.__name__, site)
    now = time.monotonic()
    with _lock:
        if now - _recent.get(key, -float('inf')) < 60:
            return
        _recent[key] = now
    reason = safe_reason(error)
    status = _safe_status(error)
    tail = '; '.join(x for x in ((f'neden: {reason}' if reason else ''), status) if x)
    # A replacement exception preserves the stack without exposing provider URLs,
    # API keys or user input carried by the original exception or its cause.
    safe = RuntimeError(kind.__name__)
    logging.getLogger('jarvis').exception(
        'İşlem başarısız: %s; %s%s', context, failure_detail(), (f'; {tail}' if tail else ''),
        exc_info=(RuntimeError, safe, None))


# Kritik işlemlerde kullanıcıya gösterilecek açıklamalar. Özel türler OSError'dan önce gelmeli.
_USER_MESSAGES = ((TimeoutError, 'Sunucu zamanında yanıt vermedi. Biraz sonra tekrar dene.'),
                  (ConnectionError, 'Bağlantı kurulamadı. İnternetini ve adresi kontrol et.'),
                  (PermissionError, 'Bu işlem için izin yok. Dosya veya klasör izinlerini kontrol et.'),
                  (FileNotFoundError, 'Gerekli dosya bulunamadı.'),
                  (IsADirectoryError, 'Bu yol bir klasör; dosya bekleniyordu.'),
                  (OSError, 'Dosya veya sistem işlemi tamamlanamadı.'),
                  (ValueError, 'Girdi geçersiz görünüyor.'),
                  (KeyError, 'Beklenen bilgi bulunamadı.'),
                  (TypeError, 'İşlem beklenen veri türüyle uyuşmadı.'))


def user_message(exc=None) -> str:
    """Kritik işlemlerde kullanıcıya gösterilecek anlaşılır açıklama (ham mesaj asla gösterilmez)."""
    if exc is None:
        exc = sys.exc_info()[1]
    if exc is None:
        return 'İşlem tamamlanamadı.'
    status = _safe_status(exc)
    suffix = f' ({status})' if status else ''
    for kinds, text in _USER_MESSAGES:
        if isinstance(exc, kinds):
            return text + suffix
    return 'İşlem tamamlanamadı.' + suffix
