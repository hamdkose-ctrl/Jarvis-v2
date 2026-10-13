"""Jarvis'in kendi işlemleri: sesle sayfa açma, güvenli ayarları değiştirme, bakım (yeniden başlat, klasör aç).

Ayarlar YALNIZCA aşağıdaki güvenli listeden değişir: anahtarlar, gizlilik ve izinler sesle değiştirilemez.
Arayüz işleri (sayfa, küçük Jarvis, tam ekran, yeniden başlatma) motorun emit() olayıyla web tarafına iletilir.
"""
from __future__ import annotations

import os
import re
import sys

from config import DATA_DIR, load_settings, save_settings

# ------------------------------------------------------------------ sayfalar
# (kalıp, üst sekme, alt sayfa, sesli ad). İlk liste: yalnızca arayüzde olan adlar ("hafızayı aç" yeterli).
_PAGES_ALWAYS = [
    (r"komut merkez\w*|ana sayfa\w*|ana ekran\w*", "home", "", "Ana Sayfa"),
    (r"(?:ai|yapay zek[aâ]) (?:çekirde\w*|ayar\w*)|çekirdek\w*", "settings", "baglanti", "Yapay Zekâ ayarları"),
    (r"ses (?:ayarlar\w*|sekme\w*|sayfa\w*)", "settings", "ses", "Ses ayarları"),
    (r"entegrasyon\w*|bağlantılar\w*|anahtarlar\w*", "settings", "baglanti", "Bağlantılar"),
    (r"bilgi taban\w*", "tools", "kb", "Bilgi tabanı"),
    (r"hafıza\w*", "settings", "hafiza", "Hafıza"),
    (r"telefon (?:ayar|sayfa|bölüm|sekme)\w*", "tools", "telefon", "Telefon"),
    (r"github\w*|git hub\w*|güncelleme (?:sayfa|bölüm|sekme|ayar)\w*", "settings", "github", "GitHub ve güncelleme"),
    (r"telefon ve mesaj\w*", "settings", "iletisim", "Telefon ve mesajlar"),
    (r"ekran ve dosya\w*|kamera ayar\w*|ekran paylaşım\w* (?:ayar|sayfa|bölüm)\w*", "settings", "ekran", "Ekran ve dosyalar"),
    (r"hesap(?!\s*makine)\w*", "settings", "kullanici", "Hesap ve gizlilik"),
    (r"ayarlar\w*|sistem ayarlar\w*", "settings", "genel", "Ayarlar"),
    (r"gizlilik\w*|güvenlik\w*", "settings", "guvenlik", "Güvenlik"),
    (r"karakter\w*|kullanıcılar\w*", "settings", "kullanici", "Kullanıcı"),
    (r"görsel analiz\w*", "vision", "", "Görsel Analiz"),
    (r"uygulamalar\w*", "tools", "", "Araçlar"),
    (r"çalışma modu\w*|ders çalışma\w*|çalışma sayfa\w*", "study", "", "Çalışma"),
    (r"notlar\w*|not defter\w*|not (?:sayfa|sekme|ekran)\w*", "tools", "takvim", "Notlar"),
    (r"takvim\w*", "tools", "takvim", "Takvim"),
    (r"sistem tarama\w*", "tools", "tarama", "Sistem Taraması"),
    (r"gelişim rapor\w*", "tools", "rapor", "Gelişim Raporu"),
    (r"hakkında\w*", "settings", "hakkinda", "Hakkında"),
    (r"araçlar\w*", "tools", "", "Araçlar"),
    (r"yapay zek[aâ]\w*", "settings", "ai", "Yapay zekâ"),
    (r"menü\w*", "menu", "", "Menü"),   # en sonda: "ayarlar menüsü" gibi özel adlar önce eşleşir
]
# İkinci liste: başka komutlarla karışır ("takvimi aç" Google Takvim'i açar), yalnızca "sayfa/sekme" denince
_PAGES_NEED_WORD = [
    (r"sohbet\w*", "chat", "", "Sohbet"),
    (r"dosya\w*", "files", "", "Dosyalar"),
    (r"mesaj\w*|whatsapp\w*", "tools", "mesaj", "Mesajlar"),
    (r"görev\w*", "tools", "takvim", "Görevler"),
    (r"takvim\w*", "tools", "takvim", "Takvim"),
    (r"telefon\w*", "tools", "telefon", "Telefon"),
    (r"ses\w*", "settings", "ses", "Ses ayarları"),
]
_OPEN = r"(?:aç\w*|göster\w*|getir\w*|git\w*|geç\w*|dön\w*)"
_PAGE_WORD = r"(?:sayfa\w*|sekme\w*|ekran\w*|bölüm\w*|menü\w*)"


def _page(t: str) -> tuple[str, str, str] | None:
    if not re.search(rf"\b{_OPEN}(?:\s+(?:lütfen|lutfen))?\s*$", t):
        return None
    if re.search(r"\b(?:pc|bilgisayar|windows)['’]?(?:in|ın|un|ün)?\s+(?:ayar|not defter|dosya|(?:ses|gizlilik|güvenlik|uygulama|sistem)\s+ayar)", t) and not re.search(r"\bjarvis", t):
        return None   # "pc ayarlar / pc not defteri / windows ayarları": Windows uygulaması, Jarvis sayfası değil
    has_word = re.search(rf"\b{_PAGE_WORD}", t) or re.search(r"\b(?:git\w*|geç\w*|dön\w*)\s*$", t)
    for pats, need in ((_PAGES_ALWAYS, False), (_PAGES_NEED_WORD, True)):
        for pat, top, sub, name in pats:
            if re.search(rf"\b(?:{pat})", t) and (has_word or not need):
                return top, sub, name
    return None


# ------------------------------------------------------------------ ayarlar (güvenli liste)
_SPEED = {"hızlı": 600, "dengeli": 1100, "normal": 1100, "sabırlı": 1700, "yavaş": 1700}


def _onoff(t: str) -> bool | None:
    if re.search(r"\b(?:kapat\w*|kapa\b|kaldır\w*|durdur\w*|istemiyorum|olmasın|gizle\w*|sustur\w*)", t):
        return False
    if re.search(r"\b(?:aç\w*|başlat\w*|etkinleştir\w*|olsun|göster\w*|getir\w*)", t):
        return True
    return None


def _num(t: str) -> int | None:
    m = re.search(r"\b(\d{1,3})\b", t)
    return int(m.group(1)) if m else None


def _settings(t: str, emit) -> str | None:
    s = load_settings()
    # uyanma hassasiyeti (1 zor … 5 çok kolay)
    if re.search(r"hassasiyet\w*|kolay uyan\w*|zor uyan\w*|daha (?:kolay|zor) uyan", t) and not re.search(r"mikrofon", t):
        cur = int(s.get("wake_sensitivity") or 3)
        n = _num(t)
        if n is not None and 1 <= n <= 5:
            new = n
        elif re.search(r"artır|arttır|yükselt|kolay uyan|daha kolay", t):
            new = min(5, cur + 1)
        elif re.search(r"azalt|düşür|zor uyan|daha zor", t):
            new = max(1, cur - 1)
        else:
            return f"Uyanma hassasiyeti şu an {cur} (1 zor uyanır, 5 çok kolay uyanır). Artırayım mı, azaltayım mı?"
        save_settings(wake_sensitivity=new)
        if new == cur:
            return f"Uyanma hassasiyeti zaten {cur} (1 zor uyanır, 5 çok kolay uyanır)."
        return f"Uyanma hassasiyetini {cur} seviyesinden {new} seviyesine aldım (1 zor uyanır, 5 çok kolay uyanır)."
    # cevap hızı (sözün bitti sayılması için beklenen sessizlik)
    if re.search(r"cevap hız\w*|söz\w* kesme|beni (?:daha çok|biraz) bekle|acele etme", t):
        m = re.search(r"\b(hızlı|dengeli|normal|sabırlı|yavaş)\b", t)
        if m:
            key = m.group(1)
        elif re.search(r"söz\w* kesme|bekle|acele etme", t):
            key = "sabırlı"
        else:
            cur = int(s.get("live_silence_ms") or 1100)
            name = next((k for k, v in _SPEED.items() if v == cur), f"{cur} ms")
            return f"Cevap hızı şu an {name}. Hızlı, dengeli ya da sabırlı yapabilirim."
        save_settings(live_silence_ms=_SPEED[key])
        return f"Cevap hızını {key} yaptım; bir sonraki konuşmada geçerli olur."
    # uyanma sesi
    if re.search(r"uyanma ses\w*|bip ses\w*|dinleme ses\w*", t):
        on = _onoff(t)
        if on is None:
            return "Uyanma sesini açayım mı, kapatayım mı?"
        save_settings(live_beep=on)
        return f"Uyanma sesini {'açtım' if on else 'kapattım'}."
    # konuşmalardan öğrenme
    if re.search(r"(?:konuşmalar\w*dan|sohbet\w*den) öğren\w*|otomatik öğren\w*", t):
        on = _onoff(t)
        if on is None:
            return "Konuşmalarından öğrenmeyi açayım mı, kapatayım mı?"
        save_settings(learn_from_chat=on)
        return "Konuşmalarından öğrenmeyi " + ("açtım; öğrendiklerimi önce onayına sunarım." if on else "kapattım.")
    # küçük Jarvis
    if re.search(r"küçük jarvis\w*|küçük pencere\w*|köşedeki jarvis\w*|mini jarvis\w*", t):
        on = _onoff(t)
        if on is None:
            return "Küçük Jarvis'i göstereyim mi, gizleyeyim mi?"
        emit("widget", "show" if on else "hide")
        return "Küçük Jarvis'i " + ("gösteriyorum (ana pencere açıkken görünmez)." if on else "gizledim.")
    # tam ekran
    if re.search(r"tam ekran\w*|pencere mod\w*|pencereye (?:al|dön|geç)\w*", t):
        full = bool(re.search(r"tam ekran\w*\s+(?:yap|aç|geç|ol)\w*|tam ekrana", t)) and not re.search(r"tam ekran\w*\s+(?:kapat|çık)", t)
        if re.search(r"pencere mod|pencereye|tam ekrandan çık|tam ekran\w*\s+kapat", t):
            full = False
        emit("win", "full" if full else "window")
        return "Tam ekrana alıyorum." if full else "Pencere moduna alıyorum."
    # açık kalma süresi
    if re.search(r"açık kalma süre\w*|dinleme süre\w*", t):
        n = _num(t)
        if n is None:
            return f"Açık kalma süresi şu an {int(s.get('live_idle_seconds') or 90)} saniye. Kaç saniye yapayım?"
        n = max(15, min(600, n * 60 if re.search(r"dakika", t) else n))
        save_settings(live_idle_seconds=n)
        return f"Konuşma bittikten sonra {n} saniye açık kalacağım."
    # canlı konuşma modu
    if re.search(r"canlı (?:konuşma\w*|mod\w*)", t):
        on = _onoff(t)
        if on is None:
            return "Canlı konuşmayı açayım mı, kapatayım mı?"
        save_settings(live_mode=on)
        return f"Canlı konuşmayı {'açtım' if on else 'kapattım'}. Geçerli olması için “kendini yeniden başlat” de."
    return None


# ------------------------------------------------------------------ arayüz görünümü (hologram)
_TONES = {"mavi": ("blue", "Mavi"), "turkuaz": ("turquoise", "Turkuaz"), "sarı": ("yellow", "Sarı")}
_VERB = r"(?:yap\w*|olsun|seç\w*|değiştir\w*|geç\w*|aç\w*|göster\w*)"


def _ui(t: str, emit) -> str | None:
    """Ana ekran görünümü: hologram rengi, arka plan, açılışı tekrar oynatma, animasyonu açıp kapatma.
    Yalnız tarayıcıdaki görünümü değiştirir; model çağrısı yok. Tarayıcı yalnız beyaz listedeki değerleri uygular."""
    if re.search(r"(?:hologram\w*|silüet\w*|büst\w*)", t) and re.search(rf"\b{_VERB}\b", t):
        m = re.search(r"\b(mavi|turkuaz|sarı)\b", t)
        if m and not re.search(r"dağ\w*|arka\s*plan", t):
            key, name = _TONES[m.group(1)]
            emit("ui", f"hologramtone|{key}")
            return f"Hologram rengini {name.lower()} yaptım."
    m = re.search(r"\b(lav|mavi)\s+dağ\w*", t)
    if m and re.search(rf"\b{_VERB}\b", t):
        lava = m.group(1) == "lav"
        emit("ui", f"hologrambg|{'lava' if lava else 'mountains'}")
        return "Arka planı lav dağları yaptım." if lava else "Arka planı mavi dağlar yaptım."
    if re.search(r"(?:açılış\w*|animasyon\w*|hologram\w*)\s+(?:tekrar|yeniden)\s+(?:oynat|başlat|izlet|göster)\w*", t):
        emit("ui", "bustreplay|")
        return "Açılış animasyonunu baştan oynatıyorum."
    if re.search(r"(?:ana ekran|hologram)\s+animasyon\w*", t):
        on = _onoff(t)
        if on is None:
            return "Ana ekran animasyonunu açayım mı, kapatayım mı?"
        emit("ui", f"nxbust|{1 if on else 0}")
        return "Ana ekran animasyonunu " + ("açtım." if on else "kapattım; durağan görünüm kullanılacak.")
    return None


# ------------------------------------------------------------------ bakım
def _maintenance(t: str, emit) -> str | None:
    if re.search(r"(?:kendini|jarvis\w*|sistemini|uygulamayı)\s+(?:yeniden|tekrar)\s+başlat\w*|^yeniden başla\w*$", t) \
            and not re.search(r"bilgisayar\w*|pc\b|windows", t):
        emit("restart", "")
        return "Yeniden başlatıyorum, birkaç saniye içinde geri döneceğim."
    if re.search(r"(?:log|kayıt|günlük)\s+(?:klasör\w*|dosya\w*)\s+aç\w*|veri klasör\w*\s+aç\w*|jarvis klasör\w*\s+aç\w*", t):
        target = DATA_DIR / "jarvis.log" if re.search(r"dosya", t) else DATA_DIR
        try:
            if sys.platform.startswith("win"):
                os.startfile(str(target))           # type: ignore[attr-defined]  # noqa: S606
            else:
                import subprocess
                subprocess.Popen(["xdg-open", str(target)])
        except OSError as e:
            return f"Açamadım: {e}"
        return f"{'Log dosyasını' if target.suffix else 'Jarvis veri klasörünü'} açtım."
    return None


def handle(cmd_lower: str, emit) -> str | None:
    """Jarvis'in kendi işlemleri; komut buraya ait değilse None."""
    t = cmd_lower.strip(" .!?")
    if re.fullmatch(r"(?:yeni\s+(?:bir\s+)?kullanıcı\s+(?:aç|ekle|oluştur)|kullanıcı\s+(?:ekleme|oluşturma)\s+(?:sayfasını|ekranını)\s+aç)", t):
        emit("nav", "settings|kullanici")
        return "Kullanıcılar sayfasını açıyorum. Yeni Kullanıcı düğmesinden adını yazarak ekleyebilirsin."
    r = _maintenance(t, emit)
    if r:
        return r
    r = _settings(t, emit)
    if r:
        return r
    r = _ui(t, emit)
    if r:
        return r
    pg = _page(t)
    if pg:
        top, sub, name = pg
        emit("nav", f"{top}|{sub}")
        return f"{name} sayfasını açıyorum."
    return None
