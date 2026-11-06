"""WhatsApp mesajı gönderme (Windows masaüstü uygulaması).

Tek yol vardır: kişinin **kayıtlı numarası**. Numara yoksa gönderim başlamaz.

Eski ikinci yol (numarasız: uygulamayı aç, arama kutusuna adı yaz, ilk sohbet sonucunu seç, metni
yapıştır, Enter) bilinçli olarak kaldırıldı: arama sonucunun ilk satırı kullanıcının kastettiği kişi
olabilir de olmayabilir de, ve onay ile gönderim arasındaki bu belirsizlik geri alınamaz bir dış
etkiye (yanlış kişiye mesaj) dönüşüyordu. Alıcı çözümlemesi `contact_matches` ile yalnız kayıtlı
defterde ve yalnız tekil eşleşmede yapılır (`find_contact`); numara yoksa çağrı hiç başlamaz.
Gönderme sırasında klavye ve fareye dokunulmamalıdır. Fareyi ekranın köşesine sürmek işlemi durdurur (pyautogui güvenliği).
"""
from __future__ import annotations
from modules.diagnostics import record_failure as _record_failure

import os
import re
import time
import threading
from urllib.parse import quote

from modules import requests_state

# BRAIN-03 dilim 2: "bu bir WhatsApp mesajı mı" ve "alıcı/gövde nedir" hükümleri bu modülden
# kaldırıldı. Anlam kararı `brain_understanding` (`message.send`), biçim hükmü `brain_core_map`,
# oturum/onay mevcut `pending_msg` protokolüdür. Burada kalanlar yürütücüdür: numara
# normalleştirme, kayıtlı kişi çözümlemesi ve gerçek gönderim.


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


_TURKISH_FOLD = str.maketrans({"ç": "c", "ğ": "g", "ı": "i", "ö": "o", "ş": "s", "ü": "u",
                              "â": "a", "î": "i", "û": "u"})


def fold_name(text: str) -> str:
    """Ad karşılaştırması için Türkçe-duyarlı katlama: "Ayşe" ve "ayse" aynı kişidir."""
    if not isinstance(text, str):
        return ""
    lowered = text.casefold().translate(_TURKISH_FOLD)
    cleaned = re.sub(r"[^a-z0-9 ]+", " ", lowered)
    return " ".join(cleaned.split())


def contact_matches(contacts: dict, name: str) -> list[tuple[str, str]]:
    """Kayıtlı defterde adı `name`e uyan kişiler: birebir eşleşme ya da tam kelime öneki.

    Bulanık (difflib) eşleştirme yoktur: "mehmet" kayıtlı "Memet"i seçmez. Yakınlık ölçüsü
    tek bir kişiyi sessizce seçmenin aracı olamaz; eşleşme ya yazılan addır ya da o adla
    başlayan tam kelimelerdir. Birden fazla kişi uyuyorsa karar kullanıcınındır.
    """
    query = fold_name(name)
    if not query or not isinstance(contacts, dict):
        return []
    exact: list[tuple[str, str]] = []
    prefixed: list[tuple[str, str]] = []
    for stored, phone in contacts.items():
        folded = fold_name(stored)
        if not folded or not phone:
            continue
        if folded == query:
            exact.append((stored, str(phone)))
        elif folded.startswith(query + " "):
            prefixed.append((stored, str(phone)))
    return sorted(exact or prefixed, key=lambda row: fold_name(row[0]))


def find_contact(contacts: dict, name: str) -> tuple[str, str] | None:
    """Yalnız **tekil** eşleşmede (ad, numara); belirsizlikte None (karar kullanıcıya)."""
    matches = contact_matches(contacts, name)
    return matches[0] if len(matches) == 1 else None


def mask_phone(phone: str | None) -> str:
    """Onay metninde gösterilecek kısa kimlik: numaranın son dört hanesi."""
    digits = re.sub(r"\D", "", str(phone or ""))
    return "…" + digits[-4:] if len(digits) >= 4 else ""


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
    if not phone:
        # Numara yoksa hiçbir uygulama açılmaz, arama kutusu kullanılmaz: ad benzerliğiyle
        # hedef seçmek yanlış kişiye mesaj riskidir (kaldırılan GUI yolu).
        return f"{name} için kayıtlı bir numara yok; mesajı göndermedim."
    if os.name != "nt":
        return "WhatsApp mesajı yalnızca Windows'ta gönderilebilir."
    import pyautogui
    try:
        requests_state.check()
        was_open = _find_window("whatsapp")
        os.startfile(f"whatsapp://send?phone={phone}&text={quote(text)}")   # type: ignore[attr-defined]
        if was_open:
            _pause(1.3)
        else:
            if not _wait_window("whatsapp"):
                return "WhatsApp penceresini bulamadım; mesajı göndermedim."
            _pause(2.2)             # sohbet ve hazır metin yüklensin
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
