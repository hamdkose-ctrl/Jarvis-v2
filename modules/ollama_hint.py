"""Ollama isteğe bağlıdır; yokluğunda ve internetin yokluğunda kullanıcıya tek, açık Türkçe mesaj."""
from __future__ import annotations

import socket
import time
import errno

from modules import failure_policy

INSTALL = "ollama.com adresinden kurup `ollama serve` ile başlat"
NO_INTERNET = "İnternet bağlantın yok, bağlanınca tekrar dene."
IMAGE = "Bu görüntü için Gemini anahtarı ya da görüntü destekli bir Ollama modeli gerekir."
_cache: dict = {}


def need(feature: str) -> str:
    return f"{feature} için Ollama yüklemelisin: {INSTALL}."


def need_local(label: str, url: str) -> str:
    """LM Studio / llama.cpp seçiliyken sunucu yoksa."""
    return (f"Yerel model için {label} sunucusu çalışmıyor ({url}). {label} içinde bir model yükleyip "
            "yerel sunucuyu başlat ya da Yapay zekâ › Ollama panelinden uç noktayı düzelt.")


def unavailable(error: BaseException) -> str | None:
    """Yalnız mevcut hata zincirindeki bağlantı reddi; ek ağ/servis yoklaması yapmaz."""
    pending, seen = [error], set()
    while pending and len(seen) < 24:
        current = pending.pop()
        if not isinstance(current, BaseException) or id(current) in seen:
            continue
        seen.add(id(current))
        if (isinstance(current, ConnectionRefusedError)
                or isinstance(current, OSError) and (
                    getattr(current, 'errno', None) == errno.ECONNREFUSED
                    or getattr(current, 'winerror', None) == 10061
                    or 'connection refused' in str(current).casefold())):
            return 'Ollama yüklenmemiş veya çalışmıyor; Ollama yüklemelisin: ' + INSTALL + '.'
        pending.extend([current.__cause__, current.__context__, getattr(current, 'reason', None)])
        pending.extend(value for value in current.args if isinstance(value, BaseException))
    return None


def _probe() -> bool:
    try:
        with socket.create_connection(("1.1.1.1", 443), timeout=1.0):
            return True
    except OSError:
        return False


def internet_up() -> bool:
    """Yalnız hata yolunda çağrılır; sonuç 10 sn saklanır."""
    now = time.monotonic()
    hit = _cache.get("up")
    if hit and now - hit[0] < 10:
        return hit[1]
    up = _probe()
    _cache["up"] = (now, up)
    return up


def offline_text(exc: BaseException) -> str | None:
    """Bulut çağrısı DNS/ağ hatasıyla düştüyse ve internet gerçekten yoksa tek cümle; yerel model hatası sayılmaz."""
    if type(exc).__name__ in ("LocalModelError", "ImageCapabilityError"):
        return None
    if failure_policy.classify(exc) not in (failure_policy.DNS, failure_policy.NETWORK):
        return None
    return None if internet_up() else NO_INTERNET
