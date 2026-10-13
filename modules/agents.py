"""'Ajanlar': Jarvis'in yetenek alanları ve komutların hangi alana girdiğini bulan sınıflandırıcı."""
from __future__ import annotations

import re

# (anahtar, simge, ad, açıklama, örnek komut)
AGENTS = [
    ("sohbet", "💬", "Sohbet ve kod", "Soru yanıtlar, kod yazar ve açıklar", "Python ile asal sayı kodu yaz"),
    ("uygulama", "🚀", "Uygulama ve sistem", "Program açar/kapatır, ses, parlaklık, kilit", "Steam aç"),
    ("medya", "🎵", "Müzik ve medya", "YouTube, Spotify, oynatma kontrolü", "YouTube'da lofi aç"),
    ("mesaj", "📲", "WhatsApp", "Kişilere mesaj yazar", "Ali'ye geliyorum diye mesaj at"),
    ("takvim", "📅", "Takvim ve görevler", "Etkinlik, hatırlatma, görev, not", "Yarın 10'da toplantı ekle"),
    ("hava", "⛅", "Hava durumu", "Konumuna göre hava söyler", "Hava nasıl?"),
    ("goruntu", "🖥", "Ekran ve kamera", "Ekranı/kamerayı görür ve yorumlar", "Ekranıma bak"),
    ("dosya", "📁", "Dosya ve belge", "Dosya bulur, düzenler, belge özetler", "Masaüstünü düzenle"),
    ("ceviri", "🌐", "Çeviri", "Metin ve belge çevirir", "Bunu İngilizceye çevir: merhaba"),
    ("google", "📧", "Gmail ve Google Takvim", "Okunmamış mail, ajanda (salt okuma)", "Okunmamış mailleri oku"),
    ("makro", "⚡", "İş akışları", "Komut zincirleri (kısayollar)", "Sabah rutini öğret"),
    ("bilgi", "📚", "Bilgi tabanı", "Eklediğin belgelerden soru yanıtlar", "Bilgi tabanında depozito ne kadar"),
]

_RULES = [
    ("bilgi", r"bilgi tabanı|belgelerimde|belgelerimden"),
    ("makro", r"kısayol|makro|rutin|iş akışı"),
    ("google", r"\bmail|e-?posta|ajanda|gelen kutu"),
    ("mesaj", r"whatsapp|mesaj|kişi(?:ler)? (?:ekle|sil|listele)|rehber"),
    ("medya", r"youtube|spotify|müzik|şarkı|parça|videoyu|oynat"),
    ("ceviri", r"çevir|tercüme"),
    ("takvim", r"takvim|hatırlat|randevu|etkinlik|toplantı|görev|yapılacak|\bnot\b|notlar|hedef|alarm"),
    ("hava", r"hava\b|hava durumu|yağmur|sıcaklık|yağış"),
    ("goruntu", r"ekran|kamera|görüntü|fotoğraf"),
    ("dosya", r"dosya|klasör|masaüstü|belge|\bpdf|docx|xlsx"),
    ("uygulama", r"\baç\b|\bkapat|\bses\b|sesi|parlaklık|kilitle|bilgisayar|sistem|uygulama|başlat"),
]


def classify(cmd_lower: str) -> str:
    for key, pat in _RULES:
        if re.search(pat, cmd_lower):
            return key
    return "sohbet"


def state(key: str, profile) -> tuple[str, str]:
    """(kısa durum yazısı, renk adı): 'good' | 'cyan' | 'warn' | 'muted'. Gerçek bağlantı ve verilerden hesaplanır."""
    from modules import google_api, tasks, vision
    d = profile.data
    if key == "goruntu":
        m = vision.mode()
        return (("Açık · " + ("kamera" if m == "camera" else "ekran")), "good") if m else ("Hazır", "cyan")
    if key == "google":
        if google_api.TOKEN.exists():
            return "Bağlı", "good"
        return ("İzin bekliyor", "warn") if google_api.CRED.exists() else ("Kurulmadı", "muted")
    if key == "mesaj":
        n = len(d.get("contacts") or {})
        return (f"{n} kişi", "good") if n else ("Kişi yok", "warn")
    if key == "takvim":
        done, total = tasks.counts(profile)
        return (f"{total - done} açık görev", "cyan") if total else ("Hazır", "cyan")
    if key == "makro":
        n = len(d.get("macros") or {})
        return (f"{n} akış", "good") if n else ("Akış yok", "muted")
    if key == "bilgi":
        n = len(d.get("kb") or [])
        return (f"{n} belge", "good") if n else ("Belge yok", "muted")
    if key == "medya":
        from modules import media
        return ("Spotify", "good") if media.spotify_installed() else ("YouTube", "cyan")
    if key == "hava":
        city = d["prefs"].get("city") or d["prefs"].get("location")
        return (str(city), "good") if city else ("Konumdan", "cyan")
    return "Hazır", "cyan"
