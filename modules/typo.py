"""Yazım hatası düzeltici: "kotrol et" -> "kontrol et", "hatirlat" -> "hatırlat".

Yalnızca Jarvis'in komut kalıplarında geçen anahtar kelimeler düzeltilir (Türkçe ekler korunur: "maylerimi" -> "maillerimi"
gibi değil, kökün başı eşleşirse "kotrolü" -> "kontrolü"). main.handle önce yazılanı olduğu gibi dener; hiçbir kalıba
uymazsa düzeltilmiş hâliyle bir kez daha dener. Böylece doğru yazılmış cümleler hiç değişmez.
"""
import re

VOCAB = sorted(set("""
    adlandır adresini adımı ajandam akabinde akşam analiz anlamadım anlamca anlamsal anlatıyor ardından ayarla
    açamadım açar açsana bayan bağlantı başlat başlatılamadı belgelerimde belgelerimden bildirim bildirimleri
    bilgi bilgisayar bilgisayarı biraz bitir bitti boşver brifing bugün bugünün bulamadım dakika dediğim
    dediğimde defterine derle dersem desem devam değiştir dilli dinle dolar dosya duraklat durdur dursun
    durumu düzenle düzenlemey düzenlemeyi e-posta ekle ekran ekrandaki eposta erkek etkinleştir etkinlik ettir
    euro evet gece geldi gelen gelmiş geri gmail google gönder görev görevi görevini görevleri görevlerim
    görevlerime görevlerimi görünmüyor görüntü görüntüsü göster günlerden günlük günümü hanım hata hatırla
    hatırlat hatırlatma hava havaalanı havai havalimanı hayır hedef hedefi hedefim hedeflerim hepsini
    hızlandır hızlı hızı ilet indirdi indirilen ingilizce internet internette iptal ismimi işaretle işim
    işyeri kadın kaldır kamera kapat kapatma kapatmayı kaydet kimim kiminle kişi kişileri klasör kontrol
    konumum konumumu konuş konuşma konuşmayı konuşuyor konuşuyorsun kopyala kullanıcı kullanıcılar
    kullanıcıları kullanıcıyı kutu kuvvet kısayol kısayollarım listele listem mail maillerimi mesaj metnini
    mute müzik nota notlar notları notlarım notlarımı notu numara numaralı numarası ofis okunmamış oluştur
    onayl outlook oynat oynatmayı oyunu oyununu parlaklık parça parçayı paylaş paylaşımı planım program
    programı programım programını randevu randevum rehbere rehberim resmini saat saati sabah sayfa sayfasını
    sesi sesimi sesini sessiz seviyesi sistem site sitesini sonra sonraki sonrakine spotify stop söyle sıfırla
    sıradaki sırala tabanı tailscale takvim takvime takvimim tamamla tamamlanan tamamlandı tarayıcıda tarih
    taşıdıklarını telefon telefona telefonu temizle topla toplantı türkçe unut uygulama uygulamasını
    uygulamayı vazgeç video videoyu whats whatsapp yabancı yaklaşan yapsana yaptım yapılacaklar yapılacaklara
    yarın yavaş yavaşlat yağacak yağmur yaşadığım yeni yeniden yeter yolla yolu youtube yüzde zaman çalıştır
    çevir çokdilli çıkar çıktı önce önceki öncekine önümüzdeki özet özeti özetle öğleden ışığı şarkı şarkıyı
    şehir şehrim şehrimi şirket
""".split()), key=len, reverse=True)

_FOLD = str.maketrans("çğıöşüâîû", "cgiosuaiu")


def _fold(s: str) -> str:
    return s.translate(_FOLD)


_VF = [(v, _fold(v)) for v in VOCAB]


def _lev1(a: str, b: str) -> bool:
    """a ile b arasında tam olarak 1 harf farkı (ekleme, silme, değiştirme ya da yan yana iki harfin yer değişmesi)."""
    if a == b or abs(len(a) - len(b)) > 1:
        return False
    if len(a) == len(b):
        diff = [i for i in range(len(a)) if a[i] != b[i]]
        if len(diff) == 1:
            return True
        return len(diff) == 2 and diff[1] == diff[0] + 1 and a[diff[0]] == b[diff[1]] and a[diff[1]] == b[diff[0]]
    if len(a) > len(b):
        a, b = b, a
    i = 0
    while i < len(a) and a[i] == b[i]:
        i += 1
    return a[i:] == b[i + 1:]


_MUTATE = {("k", "g"): "ğ", ("k", "ğ"): "ğ", ("t", "d"): "d", ("p", "b"): "b", ("ç", "c"): "c"}


def fix_word(tok: str) -> str:
    if len(tok) < 4 or not tok.isalpha():
        return tok
    ft = _fold(tok)
    for v, fv in _VF:                               # en uzun anahtar kelimeden başla
        if len(fv) >= 4 and ft.startswith(fv):
            if tok.startswith(v):
                return tok                          # doğru yazılmış (ekli hâli dahil)
            return v + tok[len(v):]                 # Türkçe karakter eksik: "hatirlat" -> "hatırlat"
    for v, fv in _VF:                               # tek harf hatası: "kotrol" -> "kontrol"
        # Kısa kelimeler (gelen, bitti, dolar, ettir…) başka kelimelerin içinde çok sık "1 harf farkla" görünür:
        # "gelecek"->"gelenek", "bitmiş"->"bittiş", "olarak"->"dolarak" gibi bozmalara yol açıyordu. Bu yüzden
        # tek harf düzeltmesi yalnızca 6+ harfli anahtar kelimelerde, ilk harf aynıyken ve ardından en fazla
        # kısa bir ek (≤3 harf) geliyorsa yapılır.
        if len(v) < 6 or ft[:1] != fv[:1]:
            continue
        for n in (len(v), len(v) + 1, len(v) - 1):
            if not (4 <= n <= len(tok)) or len(tok) - n > 3:
                continue
            head = _fold(tok[:n])
            if not _lev1(head, fv):
                continue
            if n == len(v) and head[:-1] == fv[:-1]:   # son harf yumuşaması: "muzig-i" -> "müziğ-i"
                m = _MUTATE.get((v[-1], tok[n - 1]))
                if m:
                    return v[:-1] + m + tok[n:]
            return v + tok[n:]
    return tok


def fix(text: str) -> str:
    """Komuttaki kelimeleri tek tek düzeltir; noktalama ve boşluklar korunur."""
    return re.sub(r"[a-zçğıöşüâîû]+", lambda m: fix_word(m.group(0)), text)
