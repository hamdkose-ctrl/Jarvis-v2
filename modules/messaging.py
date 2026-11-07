"""WhatsApp mesajı gönderme (Windows masaüstü uygulaması).

Tek yol vardır: kişinin **kayıtlı numarası**. Numara yoksa gönderim başlamaz.

Eski ikinci yol (numarasız: uygulamayı aç, arama kutusuna adı yaz, ilk sohbet sonucunu seç, metni
yapıştır, Enter) bilinçli olarak kaldırıldı: arama sonucunun ilk satırı kullanıcının kastettiği kişi
olabilir de olmayabilir de, ve onay ile gönderim arasındaki bu belirsizlik geri alınamaz bir dış
etkiye (yanlış kişiye mesaj) dönüşüyordu. Alıcı çözümlemesi `contact_matches` ile yalnız kayıtlı
defterde ve yalnız tekil eşleşmede yapılır (`find_contact`); numara yoksa çağrı hiç başlamaz.
Numara iki sınırda doğrulanır: çözümlemede `normalize_phone` (bozuk/metin/enjeksiyon kaydı
eşleşme sayılmaz), yürütücüde yalnız kanonik biçim (ham telefon değeri URI'ye giremez).
Gönderme sırasında klavye ve fareye dokunulmamalıdır. Fareyi ekranın köşesine sürmek işlemi durdurur (pyautogui güvenliği).
"""
from __future__ import annotations
from modules.diagnostics import record_failure as _record_failure

import os
import re
import time
import threading
from typing import Any
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

    Numara da eşleşmenin koşuludur: kayıt yalnız telefon biçimi taşıyorsa `normalize_phone`
    ile doğrulanır ve **kanonik** numara döner. Bozuk, boş, metin içeren ya da URL parametresi
    enjeksiyonu taşıyan kayıt eşleşme sayılmaz (normalize edip "kurtarmak" `&cc=90` gibi
    eklerdeki rakamları hedefe ekleyerek yanlış numara üretebilir).
    """
    matches: list[tuple[str, str]] = []
    for stored, phone in _name_rows(contacts, name):
        canonical = _canonical_record_phone(phone)
        if canonical is not None:
            matches.append((stored, canonical))
    return matches


def invalid_number_matches(contacts: dict, name: str) -> list[str]:
    """Adı eşleşip numarası geçersiz/bozuk kayıtlar: ret gerekçesini doğru söylemek için."""
    return [stored for stored, phone in _name_rows(contacts, name)
            if _canonical_record_phone(phone) is None]


# Eski/elle düzenlenmiş profil kaydı yürütücüye ham taşınmaz: yalnız telefon biçimi
# karakterleri normalize edilir; harf, &, =, #, ? gibi URL/parametre karakterleri reddedilir.
_PHONE_RECORD = re.compile(r"[+0-9(][0-9\s\-()]*")


def _canonical_record_phone(phone: Any) -> str | None:
    raw = str(phone).strip() if phone is not None else ""
    if not raw or _PHONE_RECORD.fullmatch(raw) is None:
        return None
    return normalize_phone(raw)


def _name_rows(contacts: dict, name: str) -> list[tuple[str, Any]]:
    """Tek ad eşleşme otoritesi: birebir ya da tam kelime öneki, kararlı sırada."""
    query = fold_name(name)
    if not query or not isinstance(contacts, dict):
        return []
    exact: list[tuple[str, Any]] = []
    prefixed: list[tuple[str, Any]] = []
    for stored, phone in contacts.items():
        folded = fold_name(stored)
        if not folded:
            continue
        if folded == query:
            exact.append((stored, phone))
        elif folded.startswith(query + " "):
            prefixed.append((stored, phone))
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
    # Son güvenlik sınırı: çözümleme normalize etmiş olsa bile URI'ye yalnız KANONİK numara
    # girer. Ham değer (boşluk, +, enjeksiyon karakteri, rakam dışı metin) burada reddedilir;
    # böylece URL parametresine ham telefon değeri hiçbir yoldan geçemez.
    canonical = normalize_phone(phone) if isinstance(phone, str) else None
    if canonical is None or canonical != phone:
        return f"{name} için geçerli bir numara yok; mesajı göndermedim."
    if os.name != "nt":
        return "WhatsApp mesajı yalnızca Windows'ta gönderilebilir."
    import pyautogui
    try:
        requests_state.check()
        was_open = _find_window("whatsapp")
        os.startfile(f"whatsapp://send?phone={canonical}&text={quote(text)}")   # type: ignore[attr-defined]
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
