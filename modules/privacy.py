"""Gizlilik ve güvenlik: gizlilik modları, hassas bilgi gizleme (redaction), denetim kaydı, anahtar koruma.

Modlar (Ayarlar -> privacy_mode):
  normal : bulut (Gemini) + yerel (Ollama) serbest
  gizli  : ekran/kamera ve web'e açılan işlemler kapalı; bulut modele giden metin her zaman maskelenir
  yerel  : yalnızca yerel model (Ollama); buluta hiçbir şey gitmez
"""
from __future__ import annotations
from modules.diagnostics import record_failure as _record_failure

import base64
import json
import re
import sys
import threading
from datetime import datetime

from config import DATA_DIR, load_settings

MODES = {
    "normal": "Normal — bulut ve yerel model serbest",
    "gizli": "Gizli — ekran, kamera ve web işlemleri kapalı, bulut metni maskelenir",
    "yerel": "Yalnızca yerel — hiçbir şey buluta gitmez (Ollama gerekir)",
}
AUDIT_FILE = DATA_DIR / "audit.jsonl"
_lock = threading.Lock()


def mode() -> str:
    m = str(load_settings().get("privacy_mode") or "normal")
    return m if m in MODES else "normal"


def redact_enabled() -> bool:
    return bool(load_settings().get("redact", True))


def blocked(feature: str) -> str | None:
    """feature: 'screen' | 'camera' | 'web'. Mod yasaklıyorsa kullanıcıya söylenecek cümleyi döndürür."""
    if mode() in ("gizli", "yerel"):
        names = {"screen": "Ekran paylaşımı", "camera": "Kamera", "web": "Web işlemleri"}
        return f"{names.get(feature, feature)} {MODES[mode()].split(' — ')[0].lower()} modda kapalı. Ayarlardan gizlilik modunu değiştirebilirsin."
    return None


# ---------------------------------------------------------------- redaction
def _luhn(num: str) -> bool:
    d = [int(c) for c in num][::-1]
    s = sum(d[0::2]) + sum(sum(divmod(x * 2, 10)) for x in d[1::2])
    return s % 10 == 0


_PATTERNS = [
    ("anahtar", re.compile(r"\b(?:AIza[0-9A-Za-z_\-]{30,}|sk-[A-Za-z0-9_\-]{20,}|gsk_[A-Za-z0-9_\-]{20,}|github_pat_[A-Za-z0-9_]{20,}|gh[pousr]_[A-Za-z0-9]{20,}|xox[abp]-[A-Za-z0-9\-]{10,})\b")),
    ("e-posta", re.compile(r"\b[\w.+-]+@[\w-]+(?:\.[\w-]+)+\b")),
    ("iban", re.compile(r"\bTR\d{2}(?:\s?\d{4}){5}\s?\d{2}\b", re.I)),
]
_MASKED_VALUE = r"\[(?:gizli değer|anahtar|e-posta|iban|kart|telefon|kimlik no) gizlendi\]"
_LABELED_SECRET = re.compile(
    r"(\b[\w-]*(?:belirteç|belirtec|token|secret|parola|şifre|sifre|password|passwd|api[_-]?key|anahtar)[\w-]*\b\s*[=:]\s*)"
    r"(?!" + _MASKED_VALUE + r")\S{6,}",
    re.I,
)
_BEARER = re.compile(
    r"(\bBearer[ \t]+)(?:[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+|[A-Za-z0-9._~+/-]{20,}=*)"
    r"(?![A-Za-z0-9._~+/=-])",
    re.I,
)
_CARD = re.compile(r"\b\d(?:[ -]?\d){12,18}\b")
_TCKN = re.compile(r"\b[1-9]\d{10}\b")
_PHONE = re.compile(r"(?<!\d)(?:\+?90[\s-]?)?0?5\d{2}[\s-]?\d{3}[\s-]?\d{2}[\s-]?\d{2}(?!\d)")


def redact(text: str, force: bool = False) -> str:
    """Bulut modele gitmeden önce anahtar, e-posta, IBAN, kart, T.C. no ve telefonu maskeler."""
    if not text or not (force or redact_enabled() or mode() == "gizli"):
        return text
    text = _BEARER.sub(lambda m: m.group(1) + "[gizli değer gizlendi]", text)
    text = _LABELED_SECRET.sub(lambda m: m.group(1) + "[gizli değer gizlendi]", text)
    for label, pat in _PATTERNS:
        text = pat.sub(f"[{label} gizlendi]", text)

    def card(m):
        digits = re.sub(r"\D", "", m.group(0))
        return "[kart gizlendi]" if 13 <= len(digits) <= 19 and _luhn(digits) else m.group(0)

    text = _CARD.sub(card, text)
    def phone(match):
        # A UUID hex token may end in ten phone-like digits. Keep the full
        # 32-character identifier intact; ordinary phone numbers still redact.
        start, end = match.span()
        while start and text[start-1] in "0123456789abcdefABCDEF":
            start -= 1
        while end < len(text) and text[end] in "0123456789abcdefABCDEF":
            end += 1
        token = text[start:end]
        if len(token) == 32 and re.fullmatch(r"[0-9a-fA-F]{32}", token):
            return match.group(0)
        return "[telefon gizlendi]"

    text = _PHONE.sub(phone, text)
    text = _TCKN.sub("[kimlik no gizlendi]", text)
    # Telefon/kimlik kalkınca görünür olan bitişik kart da ilk çağrıda maskelenir.
    text = _CARD.sub(card, text)
    return text


# ---------------------------------------------------------------- denetim kaydı
def audit(action: str, detail: str = "", ok: bool = True) -> None:
    """Dış dünyayı etkileyen işlemleri ~/.jarvis/audit.jsonl dosyasına yazar (mesaj gövdesi ve parola yazılmaz)."""
    row = {"ts": datetime.now().strftime("%Y-%m-%d %H:%M:%S"), "action": action,
           "detail": redact(str(detail), force=True)[:200], "ok": bool(ok)}
    try:
        with _lock:
            if AUDIT_FILE.exists() and AUDIT_FILE.stat().st_size > 1_000_000:
                AUDIT_FILE.replace(AUDIT_FILE.with_suffix(".old.jsonl"))
            with AUDIT_FILE.open("a", encoding="utf-8") as f:
                f.write(json.dumps(row, ensure_ascii=False) + "\n")
    except OSError:
        pass


def read_audit(limit: int = 100) -> list[dict]:
    try:
        lines = AUDIT_FILE.read_text(encoding="utf-8").splitlines()[-limit:]
    except OSError:
        return []
    out = []
    for ln in reversed(lines):
        try:
            out.append(json.loads(ln))
        except ValueError:
            pass
    return out


def clear_audit() -> None:
    try:
        AUDIT_FILE.unlink(missing_ok=True)
    except OSError:
        pass


# ---------------------------------------------------------------- gizli anahtar saklama
def _dpapi(data: bytes, protect: bool) -> bytes:
    import ctypes
    from ctypes import wintypes

    class BLOB(ctypes.Structure):
        _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]

    buf = ctypes.create_string_buffer(data, len(data))
    inp = BLOB(len(data), ctypes.cast(buf, ctypes.POINTER(ctypes.c_char)))
    out = BLOB()
    fn = ctypes.windll.crypt32.CryptProtectData if protect else ctypes.windll.crypt32.CryptUnprotectData
    if not fn(ctypes.byref(inp), None, None, None, None, 0, ctypes.byref(out)):
        raise OSError("DPAPI hatası")
    try:
        return ctypes.string_at(out.pbData, out.cbData)
    finally:
        ctypes.windll.kernel32.LocalFree(out.pbData)


def protect(secret: str) -> str:
    """Windows'ta DPAPI (yalnız bu kullanıcı hesabı çözebilir); diğer sistemlerde base64 (şifreleme değil, sadece göz önünde durmaz)."""
    if sys.platform == "win32":
        try:
            return "dpapi:" + base64.b64encode(_dpapi(secret.encode("utf-8"), True)).decode()
        except Exception:
            _record_failure('modules/privacy.py:protect')
            raise OSError('Windows anahtar koruması başarısız; anahtar kaydedilmedi.') from None
    return "b64:" + base64.b64encode(secret.encode("utf-8")).decode()


def unprotect(stored: str) -> str:
    stored = stored.strip()
    try:
        if stored.startswith("dpapi:"):
            return _dpapi(base64.b64decode(stored[6:]), False).decode("utf-8")
        if stored.startswith("b64:"):
            return base64.b64decode(stored[4:]).decode("utf-8")
    except Exception:
        _record_failure('modules/privacy.py:unprotect')
        return ""
    return stored          # eski düz metin dosya
