"""Finance kaynak/tarih/kanıt doğrulaması (Faz 3, `source_verification` dalı).

Bu dal sözleşmede vardı ama modülü yoktu: `entry_points` başka dalın dosyasını
gösteriyordu (`modules/finance.py:dated_rate`, `_safe_xml`), yani "kaynak doğrulama"
diye ayrı bir dal fiilen yoktu. Doğrulama kuralları `dated_rate` içinde satır arası
duruyordu; burada tek yerde toplanır ve `dated_rate` aynı fonksiyonu çağırır.

Kurallar (sözleşmedeki üç değişmez):
* Kaynak yanıtı istenen varlık/para birimi ve tarihle eşleşmezse sonuç reddedilir.
* Kanıt en az kaynak adresi, veri tarihi, okuma zamanı ve gövde özeti (sha256) taşır.
* Kaynak içeriği izin, hedef ya da yürütme yetkisi vermez: bu modül yalnız veri doğrular,
  hiçbir efekt, gönderim veya para hareketi yetkisi üretmez.

Okuma hâlâ Finance veri dalının (`public_sources.fetch`) işidir; bu modül ağa çıkmaz.
"""
from __future__ import annotations

import hashlib
import json
import time
from datetime import date
from decimal import Decimal, InvalidOperation

# Kullanıcıya yazılan kapsam: bu bir günlük kaynak kuru, banka alış/satış fiyatı değil.
EVIDENCE_SCOPE = 'Günlük kaynak kuru; anlık banka alış/satış fiyatı değildir.'


def verify_rate_evidence(data, response, *, base, quote, on_date=None):
    """Kur yanıtını doğrular ve kanıt kaydını döner. Uymayan yanıt `ValueError` ile reddedilir.

    ``data``: kaynağın JSON gövdesi (dict), ``response``: ``{'body': bytes, 'url': str}``.
    """
    if not isinstance(data, dict) or not isinstance(response, dict):
        raise ValueError('Kur yanıtı geçersiz.')
    if data.get('base') != base.upper() or data.get('quote') != quote.upper():
        raise ValueError('Kur yanıtı para birimleriyle eşleşmiyor.')
    try:
        rate = Decimal(str(data.get('rate', '')))
    except (InvalidOperation, ValueError):
        raise ValueError('Kur değeri okunamadı.') from None
    if not rate.is_finite() or rate <= 0 or not isinstance(data.get('date'), str):
        raise ValueError('Kur/değer tarihi geçersiz.')
    date.fromisoformat(data['date'])
    if on_date and data['date'] > on_date:
        raise ValueError('Kaynak istenen tarihten sonraki kuru döndürdü.')
    url = response.get('url')
    body = response.get('body')
    if not isinstance(url, str) or not url.startswith('https://') or not isinstance(body, bytes) or not body:
        raise ValueError('Kaynak adresi veya gövdesi doğrulanamadı.')
    return {'data': data, 'source': url, 'fetched_at': time.time(),
            'sha256': hashlib.sha256(body).hexdigest(), 'scope': EVIDENCE_SCOPE}


def parse_rate_body(raw):
    """Kaynak gövdesini JSON'a çevirir; bozuk gövde doğrulamaya hiç girmez."""
    try:
        data = json.loads(raw)
    except (TypeError, ValueError):
        raise ValueError('Kaynak gövdesi JSON değil.') from None
    if not isinstance(data, dict):
        raise ValueError('Kaynak gövdesi beklenen kayıt değil.')
    return data
