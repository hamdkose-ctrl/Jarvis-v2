"""WhatsApp mesajı gönderme (Windows masaüstü uygulaması).

İki yol vardır:
  1) Kişinin numarası kayıtlıysa  -> whatsapp://send?phone=...&text=... bağlantısı sohbeti mesaj yazılı açar, Enter gönderir.
  2) Numara yoksa                 -> WhatsApp açılır, arama kutusuna ad yazılır, ilk sohbet seçilir, mesaj yapıştırılıp
                                     Enter'a basılır (ekran/klavye otomasyonu; WhatsApp sürümüne göre değişebilir).
Gönderme sırasında klavye ve fareye dokunulmamalıdır. Fareyi ekranın köşesine sürmek işlemi durdurur (pyautogui güvenliği).
"""
from __future__ import annotations
from modules.diagnostics import record_failure as _record_failure

import difflib
import json
import os
import re
import subprocess
import time
import threading
from urllib.parse import quote

from modules import system_control, requests_state

WA_WORD = re.compile(r"\b(?:whats?\s?app|whatsap|wats?ap|vats?ap|vhatsap)\w*", re.I)
SEND_VERB = re.compile(r"mesaj\w*\s+(?:at|gönder|yaz|ilet)|\byaz(?:sana|ar mısın)?\b|\bgönder\w*|\bat\b|\bilet\b", re.I)

EXTRACT_SYSTEM = """Kullanıcının WhatsApp mesaj isteğini JSON'a çevir (yalnızca JSON):
{"to": "alıcı adı ya da boş", "text": "gönderilecek mesaj metni ya da boş"}
Kurallar: Alıcı adını yalın hâle getir ("Ahmet'e" -> "Ahmet", "anneme" -> "Annem", "Ayşe'ye" -> "Ayşe", "bitaneme" -> "Bitanem", "bi taneme" -> "Bi tanem").
"bir kişiye", "birine" gibi belirsiz ifadelerde to boş kalsın. Mesaj metni yoksa text boş kalsın.
Metni olduğu gibi, kullanıcının ağzından yaz; tırnak ve "diye" gibi bağlaçları atma ("nasılsın diye yaz" -> "nasılsın")."""


def _strip_wa(cmd_lower: str) -> tuple[bool, str]:
    """(WhatsApp geçiyor mu, WhatsApp sözcüğü çıkarılmış metin). Yanlış yazılmış 'wathsaap' gibi sözcükleri de yakalar."""
    if WA_WORD.search(cmd_lower):
        return True, WA_WORD.sub(" ", cmd_lower)
    for tok in re.findall(r"[a-zçğıöşü]{6,}", cmd_lower):
        if difflib.SequenceMatcher(None, tok, "whatsapp").ratio() >= 0.7:
            return True, cmd_lower.replace(tok, " ")
    return False, cmd_lower


def is_whatsapp_message(cmd_lower: str) -> bool:
    has, rest = _strip_wa(cmd_lower)
    return has and bool(SEND_VERB.search(rest))


def extract(command: str, ask) -> tuple[str, str]:
    """(alıcı, metin) döndürür; bulunamayanlar boş string."""
    try:
        raw = ask(command, EXTRACT_SYSTEM)
        data = json.loads(raw[raw.index("{"): raw.rindex("}") + 1])
        return str(data.get("to") or "").strip(), str(data.get("text") or "").strip()
    except Exception:
        _record_failure('modules/messaging.py:extract')
        return "", ""


def normalize_phone(text: str) -> str | None:
    """'0532 123 45 67' / '+90 532...' -> '905321234567' (WhatsApp biçimi). Geçersizse None."""
    digits = re.sub(r"\D", "", text)
    if text.strip().startswith("+"):
        pass
    elif len(digits) == 11 and digits.startswith("0"):
        digits = "9" + digits            # 0532... -> 90532...
    elif len(digits) == 10 and digits.startswith("5"):
        digits = "90" + digits
    return digits if 10 <= len(digits) <= 15 else None


def find_contact(contacts: dict, name: str) -> tuple[str, str] | None:
    """Kayıtlı kişiler arasında ada en yakın olanı (ad, numara) döndürür."""
    n = system_control._norm(name)
    if not n or not contacts:
        return None
    by_norm = {system_control._norm(k): k for k in contacts}
    if n in by_norm:
        return by_norm[n], contacts[by_norm[n]]
    close = difflib.get_close_matches(n, list(by_norm), n=1, cutoff=0.8)
    return (by_norm[close[0]], contacts[by_norm[close[0]]]) if close else None


def _paste(text: str) -> None:
    """Türkçe karakterler için panoya koyup Ctrl+V ile yapıştırır."""
    import pyautogui
    try:
        import pyperclip
        pyperclip.copy(text)
        pyautogui.hotkey("ctrl", "v")
    except ImportError:
        if text.isascii():
            pyautogui.write(text, interval=0.02)
        else:
            subprocess.run(["powershell", "-NoProfile", "-Command", "Set-Clipboard -Value $input"],
                           input=text.encode("utf-8"), timeout=10,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            pyautogui.hotkey("ctrl", "v")


def _find_window(part: str) -> bool:
    """Başlığında 'part' geçen görünür bir pencere var mı (yalnızca Windows)."""
    import ctypes
    from ctypes import wintypes
    user32, found = ctypes.windll.user32, []   # type: ignore[attr-defined]
    proc_t = ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)

    def cb(hwnd, _lp):
        if user32.IsWindowVisible(hwnd):
            n = user32.GetWindowTextLengthW(hwnd)
            if n:
                buf = ctypes.create_unicode_buffer(n + 1)
                user32.GetWindowTextW(hwnd, buf, n + 1)
                if part in buf.value.lower():
                    found.append(hwnd)
        return True

    user32.EnumWindows(proc_t(cb), 0)
    return bool(found)


def _pause(seconds):
    deadline = time.monotonic() + seconds
    while True:
        requests_state.check()
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return
        time.sleep(min(0.1, remaining))


def _wait_window(part: str, timeout: float = 15.0) -> bool:
    end = time.time() + timeout
    while time.time() < end:
        requests_state.check()
        try:
            if _find_window(part):
                return True
        except Exception:
            _record_failure('modules/messaging.py:_wait_window')
            return False
        _pause(0.25)
    return False


_SEND_LOCK = threading.Lock()


def send_whatsapp(name: str, text: str, phone: str | None = None) -> str:
    while True:
        requests_state.check()
        if _SEND_LOCK.acquire(timeout=0.1):
            break
    try:
        requests_state.check()
        return _send_whatsapp(name, text, phone)
    finally:
        _SEND_LOCK.release()


def _send_whatsapp(name: str, text: str, phone: str | None = None) -> str:
    """Mesajı gönderir; kullanıcıya söylenecek sonucu döndürür. (Gönderimin alındığı doğrulanamaz.)
    Sabit uzun beklemeler yerine WhatsApp penceresi görünene kadar beklenir; açıksa neredeyse hemen gönderir."""
    if os.name != "nt":
        return "WhatsApp mesajı yalnızca Windows'ta gönderilebilir."
    import pyautogui
    try:
        requests_state.check()
        was_open = _find_window("whatsapp")
        if phone:
            os.startfile(f"whatsapp://send?phone={phone}&text={quote(text)}")   # type: ignore[attr-defined]
            if was_open:
                _pause(1.3)
            else:
                if not _wait_window("whatsapp"):
                    return "WhatsApp penceresini bulamadım; mesajı göndermedim."
                _pause(2.2)             # sohbet ve hazır metin yüklensin
            requests_state.check()
            pyautogui.press("enter")
        else:
            system_control.open_application("whatsapp")
            if was_open:
                _pause(1.0)
            else:
                if not _wait_window("whatsapp"):
                    return "WhatsApp penceresini bulamadım; mesajı göndermedim."
                _pause(1.8)
            pyautogui.hotkey("ctrl", "f")        # sohbet arama kutusu
            _pause(0.4)
            _paste(name)
            _pause(1.2)
            pyautogui.press("down")              # ilk sonucu seç
            requests_state.check()
            pyautogui.press("enter")
            _pause(0.8)
            _paste(text)
            _pause(0.3)
            requests_state.check()
            pyautogui.press("enter")
        return f"{name} için WhatsApp’ta gönderme komutunu uyguladım. Mesajın teslimini doğrulayamıyorum."
    except requests_state.Cancelled:
        raise
    except pyautogui.FailSafeException:
        return "Fareyi köşeye götürdüğün için mesaj gönderimini durdurdum."
    except Exception as exc:
        _record_failure('modules/messaging.py:send_whatsapp')
        from modules.diagnostics import user_message
        return "Mesajı gönderemedim: " + user_message(exc)


_NOISE = {"aç", "ve", "mesaj", "mesajı", "at", "yaz", "gönder", "diye", "ile", "ilet", "lütfen", "bir", "şunu", "şöyle"}


def quick_parse(cmd_lower: str, contacts: dict) -> tuple[str, str] | None:
    """Kayıtlı bir kişi adı geçiyorsa LLM'e sormadan (alıcı, metin) çıkarır; geçmiyorsa None."""
    if not contacts:
        return None
    _, rest = _strip_wa(cmd_lower)
    tokens = re.findall(r"[\w'’]+", rest)
    names = {system_control._norm(k): k for k in contacts}
    for i, tok in enumerate(tokens):
        base = system_control._norm(tok.split("'")[0].split("’")[0])
        if len(base) < 3:
            continue
        for n, orig in names.items():
            if base == n or (base.startswith(n) and len(base) - len(n) <= 3) or (n.startswith(base) and len(n) - len(base) <= 1):
                words = [t for j, t in enumerate(tokens) if j != i and t.strip("'’") not in _NOISE
                         and not re.fullmatch(r"['’]?(?:tan|ten|ta|te|dan|den)", t)]
                return orig, " ".join(words).strip()
    return None
