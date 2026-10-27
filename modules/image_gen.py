"""Görsel üretimi — Cloudflare Workers AI (FLUX) üzerinden.

Neden Cloudflare: Gemini'nin güncel görsel üretim modellerinde (Nano Banana
ailesi) ÜCRETSİZ katman yok; hepsi resim başına ücretli. Jarvis'in kuralı
"ücretli sağlayıcılar otomatik havuza girmez" (`AGENTS.md`). Cloudflare
Workers AI'nin FLUX modeli (`@cf/black-forest-labs/flux-1-schnell`) kredi
kartı istemeden günlük 10.000 Neuron ücretsiz kota veriyor (bkz.
`docs/MIMARI_KURALLAR_v5.7.md` madde 4 ile aynı ruh: her kullanıcı kendi
anahtarını kullanır).

Bu modül SADECE üretim/iletişim katmanıdır: hangi görselin ("süreç özeti",
"zihin haritası" vb.) nasıl isteneceği (prompt metni) ayrı bir orkestrasyon
katmanının işi — burada yalnız "bu prompt'u gönder, PNG baytlarını getir"
vardır. Çizimi model yapar; kod hiçbir pikseli kendisi çizmez (Hamdi'nin
açık kararı: "Burada kod kullanmayacağız işlem yapmak için sadece").

Anahtar deseni `modules/llm.py`'deki `user_key`/`user_groq_key` ile birebir
aynı: kullanıcıya özel, korumalı (`privacy.protect`) dosya; kullanıcılar
arası fallback yok, otomatik ortak havuz yok.
"""
from __future__ import annotations

import json
import time

from modules import failure_policy, privacy
from modules.diagnostics import record_failure as _record_failure

MODEL = "@cf/black-forest-labs/flux-1-schnell"
_TIMEOUT = (5, 60)  # (bağlantı, okuma) saniye — görsel üretimi metne göre daha uzun sürebilir


class ImageGenError(Exception):
    def __init__(self, message: str, reason_code: str):
        super().__init__(message)
        self.reason_code = reason_code


class _HttpStatusError(RuntimeError):
    """HTTP yanıtını ortak failure_policy'nin anlayacağı güvenli şekle taşır."""
    def __init__(self, status_code: int, text: str = ""):
        super().__init__(text or f"HTTP {status_code}")
        self.status_code = status_code


def _account_file(slug: str):
    from config import DATA_DIR
    return DATA_DIR / "keys" / f"{slug}.cf_account.txt"


def _token_file(slug: str):
    from config import DATA_DIR
    return DATA_DIR / "keys" / f"{slug}.cf_token.txt"


def user_cloudflare_account(slug: str | None) -> str:
    if not slug:
        return ""
    f = _account_file(slug)
    try:
        return privacy.unprotect(f.read_text(encoding="utf-8")).strip() if f.exists() else ""
    except (OSError, ValueError):
        _record_failure('modules/image_gen.py:user_cloudflare_account')
        return ""


def user_cloudflare_token(slug: str | None) -> str:
    if not slug:
        return ""
    f = _token_file(slug)
    try:
        return privacy.unprotect(f.read_text(encoding="utf-8")).strip() if f.exists() else ""
    except (OSError, ValueError):
        _record_failure('modules/image_gen.py:user_cloudflare_token')
        return ""


def set_user_cloudflare(slug: str, account_id: str | None, api_token: str | None) -> None:
    """Kullanıcının kendi Cloudflare hesap kimliği + API token'ını kaydeder.

    Her iki değer de boş verilirse yalnız o kullanıcının kayıtlı bilgisi silinir.
    """
    af, tf = _account_file(slug), _token_file(slug)
    if account_id and account_id.strip():
        af.parent.mkdir(exist_ok=True)
        af.write_text(privacy.protect(account_id.strip()), encoding="utf-8")
    elif af.exists():
        af.unlink()
    if api_token and api_token.strip():
        tf.parent.mkdir(exist_ok=True)
        tf.write_text(privacy.protect(api_token.strip()), encoding="utf-8")
    elif tf.exists():
        tf.unlink()


def key_state(slug: str | None) -> dict:
    """UI/tanılama için durum; anahtarı/token'ı dışarı sızdırmaz."""
    account = user_cloudflare_account(slug)
    token = user_cloudflare_token(slug)
    return {"user": slug or "", "configured": bool(account and token), "provider": "cloudflare"}


def generate_image(prompt: str, *, slug: str, steps: int = 4, _session=None) -> bytes:
    """Verilen metin istemiyle bir görsel üretir, PNG baytlarını döndürür.

    `slug` zorunludur: anahtar kullanıcıya özeldir, ortak/varsayılan
    anahtara düşülmez (`llm.py`'deki kuralla aynı). `_session` yalnız
    testler için — gerçek `requests` çağrısını taklit etmeye yarar.
    """
    if not prompt or not prompt.strip():
        raise ImageGenError("Boş istem ile görsel üretilemez.", "EMPTY_PROMPT")
    if not slug:
        raise ImageGenError("Kullanıcı bağlamı olmadan görsel üretilemez.", "NO_USER")

    account = user_cloudflare_account(slug)
    token = user_cloudflare_token(slug)
    if not account or not token:
        raise ImageGenError(
            "Bu kullanıcı için Cloudflare hesap kimliği/API token tanımlı değil.",
            "NO_KEY",
        )

    url = f"https://api.cloudflare.com/client/v4/accounts/{account}/ai/run/{MODEL}"
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    body = {"prompt": prompt.strip(), "steps": max(1, min(steps, 8))}

    session = _session
    if session is None:
        import requests
        session = requests

    try:
        resp = session.post(url, headers=headers, data=json.dumps(body), timeout=_TIMEOUT)
    except Exception as exc:
        _record_failure('modules/image_gen.py:generate_image:request')
        category = failure_policy.classify(exc)
        reason = "NETWORK_ERROR" if category in {
            failure_policy.DNS, failure_policy.NETWORK, failure_policy.TIMEOUT
        } else "PROVIDER_ERROR"
        message = "Cloudflare'e ulaşılamadı." if reason == "NETWORK_ERROR" else "Cloudflare isteği başarısız oldu."
        raise ImageGenError(message, reason) from exc

    if resp.status_code != 200:
        raw_text = getattr(resp, "text", "")
        category = failure_policy.classify(_HttpStatusError(resp.status_code, raw_text))
        if category == failure_policy.AUTH:
            raise ImageGenError("Cloudflare kimlik doğrulaması başarısız (token/hesap kontrolü).", "AUTH_FAILED")
        if category in (failure_policy.RATE_LIMIT, failure_policy.QUOTA_EXHAUSTED):
            raise ImageGenError("Günlük ücretsiz Neuron kotası dolmuş olabilir.", "QUOTA_EXCEEDED")
        raise ImageGenError(f"Cloudflare hata döndürdü (HTTP {resp.status_code}).", "PROVIDER_ERROR")

    content_type = (resp.headers.get("content-type") or "").lower()
    if "image/" in content_type:
        data = resp.content
        if not data:
            raise ImageGenError("Cloudflare boş görsel döndürdü.", "EMPTY_RESPONSE")
        return data

    # Bazı Workers AI uç noktaları JSON içinde base64 döndürür.
    try:
        payload = resp.json()
    except ValueError:
        raise ImageGenError("Beklenmeyen yanıt biçimi.", "UNEXPECTED_FORMAT")
    image_b64 = (
        (payload.get("result") or {}).get("image")
        if isinstance(payload, dict) else None
    )
    if not image_b64:
        raise ImageGenError("Yanıtta görsel verisi bulunamadı.", "NO_IMAGE_DATA")
    import base64
    try:
        return base64.b64decode(image_b64)
    except (ValueError, TypeError):
        raise ImageGenError("Görsel verisi çözümlenemedi.", "DECODE_ERROR")
