"""Core güvenlik şeması (A10): tek izin karar noktası.

Kullanıcı kararı: "Brain anlar, Core izin verir, el yapar." Bugün risk kontrolü,
sandbox sınırı ve bütçe ayrı modüllerde dağılmıştı; burada tek karara indirilir.

`decide(action)` → serbest | ask | forbid. Yan etki yaratmaz, izin vermez; yalnız
mevcut sahiplerin (onay akışı, sandbox) kararını tek yerde toplar.
"""
from __future__ import annotations

from pathlib import Path

RISKY = ("sil", "kaldır", "ödeme", "gönder", "onayla", "paylaş", "yayınla", "iptal", "sıfırla")
FORBIDDEN = ("şifre", "password", "banka", "kredi kartı", "cvv", "pin kodu")
SANDBOX = Path.home() / ".jarvis" / "sandbox"


def _fold(text: str) -> str:
    table = str.maketrans("ıİşŞçÇğĞüÜöÖ", "iissccgguuoo")
    return " ".join(str(text or "").casefold().translate(table).split())


def decide(action: dict) -> dict:
    """Eylem için tek karar: {'verdict': free|ask|forbid, 'reason': ...}."""
    kind = _fold(action.get("kind") or action.get("capability") or "")
    label = _fold(action.get("label") or action.get("target") or "")
    text = f"{kind} {label}".strip()
    if any(word in text for word in (_fold(item) for item in FORBIDDEN)):
        return {"verdict": "forbid", "reason": "şifre/banka işlemi: Jarvis hiç yapmaz"}
    path = action.get("path")
    if path and not _inside_sandbox(str(path)):
        return {"verdict": "forbid", "reason": "yazma yalnız deneme klasörüne (~/.jarvis/sandbox)"}
    if any(word in text for word in (_fold(item) for item in RISKY)):
        return {"verdict": "ask", "reason": "geri alınamaz etki: önce onay"}
    return {"verdict": "free", "reason": "okuma veya geri alınabilir adım"}


def _inside_sandbox(path: str) -> bool:
    try:
        return Path(path).expanduser().resolve().is_relative_to(SANDBOX.resolve())
    except (OSError, ValueError):
        from modules.diagnostics import record_failure as _record_failure
        _record_failure("modules/core_policy.py:_inside_sandbox")
        return False


def allow_write(path: str) -> bool:
    return _inside_sandbox(path)
