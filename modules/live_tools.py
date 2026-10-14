"""Fixed Live tool schemas and canonical requests; no microphone or session I/O."""
from __future__ import annotations

DEFAULT_VOICE = "Charon"
VOICE_INFO = {                  # Ses sekmesinde gösterilen 6 ses: 3 erkek, 3 kadın; her biri kendi tarzında
    "Charon": "Erkek · sakin ve net", "Puck": "Erkek · canlı", "Fenrir": "Erkek · enerjik",
    "Kore": "Kadın · kararlı", "Aoede": "Kadın · rahat", "Zephyr": "Kadın · parlak",
}
VOICES = tuple(VOICE_INFO)

TOOL_DESCRIPTION = (
    "Bilgisayarda ya da kullanıcının verilerinde bir iş yapar ve sonucunu metin olarak döndürür. Aşağıdaki özel "
    "araçların kapsamadığı her iş için çağır: e-posta (Gmail/Outlook) okuma, takvim, dosya/PDF bulma-açma-özetleme-"
    "çevirme-telefona gönderme, WhatsApp mesajı, hava durumu, ekranı analiz etme, ekran/kamera paylaşımını açma-kapatma ('paylaşımı kapat'), güncel fiyat/döviz/haber/internet "
    "araması, iş ve proje takibi, Jarvis'in KENDİ işleri (sayfalarını açma: 'hafıza sayfasını aç'; ayarları: uyanma "
    "hassasiyeti, cevap hızı, uyanma sesi, küçük Jarvis, tam ekran, açık kalma süresi; 'kendini yeniden başlat'; "
    "sistem taraması; log klasörü), görev listesini okuma/tamamlama, ev-iş devir listesini okuma, kullanıcı değiştirme, uyku moduna geçme, bilgisayarı kapatma, "
    "Jarvis içindeki not, görev, kaynak, ders, tema, sağlayıcı ve mikrofon işlemleri; açık pencereleri listeleme, "
    "hedef pencereyi öne getirme/küçültme/büyütme ve hedefte yeni sekme, arama, kopyalama/yapıştırma gibi kısayollar. "
    "Şifreli geliştirme modu, Jarvis kaynaklarını inceleme/düzenleme, görsel taslak ve revizyon da bu araçtadır. "
    "Geliştirme modu açıksa 'bunu değiştir', 'devam et', 'görsel ver' gibi takip isteklerini komut aracına ilet. "
    "Kaynağı araçla okumadan kodu değiştirdiğini veya testin geçtiğini söyleme. "
    "Silme ve sağlayıcı değişimi onay ister; kullanıcı onayı gelmeden tekrar çağırıp onay uydurma. "
    "göreli ayarlar (parlaklığı kıs, sesi aç). 'istek' alanına kullanıcının sözünü OLDUĞU GİBİ, değiştirmeden yaz. "
    "Sonuç bir soru içeriyorsa (örn. 'Kime göndereyim?') kullanıcıya sor ve cevabını yine bu araçla ilet. Sohbet, "
    "selamlaşma, genel bilgi ve açıklama istekleri için ÇAĞIRMA."
)


def _schema(**props):
    from google.genai import types
    return types.Schema(type="OBJECT", required=list(props), properties={
        k: types.Schema(type=v[0], description=v[1]) for k, v in props.items()})


# Sık işler için ayrı, tek işli araçlar: model bunları genel `komut`tan çok daha güvenilir çağırıyor.
# Her biri, mevcut komut sisteminin kesin anladığı kalıp bir cümleye çevrilip main.handle'a gider.
_MEDIA = {"durdur": "müziği durdur", "oynat": "müziği oynat", "sonraki": "sonraki şarkı", "önceki": "önceki şarkı"}
TOOLS = {
    "komut": (TOOL_DESCRIPTION, _schema(istek=("STRING", "Kullanıcının sözü, olduğu gibi."))),
    "ses_ayarla": ("Bilgisayarın ses seviyesini belirli bir yüzdeye ayarlar.",
                   _schema(seviye=("INTEGER", "0-100 arası yüzde."))),
    "sessiz": ("Bilgisayarın sesini tamamen kapatır (sessize alır) ya da sessizden çıkarır. 'Sessize al', 'sesi kapat' -> "
               "durum='kapat'; 'sessizi kaldır', 'sesi geri aç' -> durum='ac'. Jarvis'in kendisinin susması için DEĞİL "
               "('sus', 'yeter' denince sadece konuşmayı bırak).",
               _schema(durum=("STRING", "'kapat' (sessize al) ya da 'ac' (sessizden çıkar)."))),
    "parlaklik_ayarla": ("Ekran parlaklığını belirli bir yüzdeye ayarlar.",
                         _schema(seviye=("INTEGER", "0-100 arası yüzde."))),
    "jarvis_kapat": ("YALNIZCA Jarvis uygulamasını kapatır. Kullanıcı 'Jarvis'i kapat', 'kendini kapat' veya "
                      "'uygulamayı kapat' dediğinde bunu çağır. Bilgisayarı/PC'yi/Windows'u kapatma isteğinde ASLA "
                      "çağırma; o işlem `komut` aracından onay alınarak yapılır.", _schema()),
    "uygulama_ac": ("Bilgisayarda kurulu bir uygulamayı ya da programı açar (Steam, Chrome, Word…). YouTube yalnızca "
                    "'YouTube aç' denmişse de bu araçla açılır; bu istek müzik çalma isteği değildir. Takvim, mail, "
                    "hava durumu, notlar Jarvis'in kendi özellikleridir, uygulama DEĞİLDİR: 'takvimi aç' / 'takvime bak' "
                    "için `komut` aracına 'bugün takvimimde ne var', mail için 'maillerimi kontrol et' yaz.",
                    _schema(ad=("STRING", "Uygulamanın adı."))),
    "uygulama_kapat": ("Açık bir uygulamayı kapatır.", _schema(ad=("STRING", "Uygulamanın adı."))),
    "medya": ("Çalan müziği/videoyu kontrol eder.",
              _schema(eylem=("STRING", "durdur, oynat, sonraki ya da önceki"))),
    "not_ekle": ("Kullanıcının not defterine not ekler. Kullanıcı bir şeyi not etmek/unutmamak istediğinde çağır.",
                 _schema(metin=("STRING", "Notun metni; 'not ekle' gibi komut sözcükleri olmadan."))),
    "hatirlatma_ekle": ("Belirli bir zamanda hatırlatma/takvim kaydı ekler.",
                        _schema(metin=("STRING", "Neyin hatırlatılacağı."),
                                zaman=("STRING", "Zaman, kullanıcının söylediği gibi: 'yarın saat 10'da', 'pazartesi', '2 saat sonra'. Gün ya da saat söylenmediyse önce kullanıcıya sor."))),
    "muzik_cal": ("Müzik, şarkı ya da belirli bir video ÇALAR: YouTube'da arar ve ilk sonucu açıp oynatır. Kullanıcı yalnızca "
                  "'YouTube aç' derse BUNU ÇAĞIRMA; uygulama_ac ile YouTube'u aç. Kullanıcı 'müzik aç', "
                  "'şarkı çal', 'X'in şarkısını aç', 'eski şarkılar dinleyelim', 'YouTube'dan müzik aç', 'komik video aç' "
                  "derse MUTLAKA bunu çağır; çağırmadan 'açıyorum', 'oynatıyorum' deme.",
                  _schema(sorgu=("STRING", "Aranacak şey: şarkı, sanatçı, tür ya da video konusu. Kullanıcı bir şey "
                                           "belirtmediyse uygun bir arama yaz (örn. 'eski türkçe pop şarkılar'); boş bırakma."),
                          platform=("STRING", "'youtube' (varsayılan) ya da kullanıcı açıkça isterse 'spotify'."))),
    "gorev_ekle": ("Yapılacak bir işi görev listesine ya da ev-iş devir listesine ekler. Kullanıcı 'görevlere ekle', "
                   "'yarın işte şuna bakacağız', 'bunu evde hallederim', 'iş notu olarak ekle', 'pazartesi işte …' gibi "
                   "ileride yapılacak bir işten bahsedip kaydetmeni istediğinde çağır.",
                   _schema(metin=("STRING", "Yapılacak iş; 'ekle', 'görev' gibi komut sözcükleri olmadan."),
                           yer=("STRING", "'iş' (iş yerinde yapılacak), 'ev' (evde yapılacak) ya da 'genel' (yer belirtilmediyse)."),
                           zaman=("STRING", "Ne zaman: 'bugün', 'yarın', gün adı ('pazartesi') ya da söylenmediyse boş."))),
    "kural_ogren": ("Kullanıcı sana KALICI bir kural ya da tercih öğrettiğinde çağır: 'bundan sonra …', 'her zaman …', "
                    "'… deyince … yap', 'bana … deme', 'cevapların kısa olsun'. Tek seferlik istekler ve sohbet için ÇAĞIRMA.",
                    _schema(kural=("STRING", "Kural; tek kısa cümle, emir kipiyle ve kullanıcının sözüne sadık: "
                                             "'Takvimi aç denince Google Takvim'i aç.'"))),
    "yanlis_duyma": ("Kullanıcı bir önceki sözünü yanlış duyduğunu/anladığını söyleyip aslında ne dediğini söylerse çağır "
                     "('yanlış anladın, takvimi aç dedim', 'hayır, … dedim'). Bir önceki söz ile doğrusu eşleştirilip "
                     "öğrenilir; sonra kullanıcının asıl isteğini de yerine getir.",
                     _schema(dogru=("STRING", "Kullanıcının aslında söylediği söz, kısa ve olduğu gibi (ör. 'takvimi aç')."))),
    "ses_degistir": ("Jarvis'in kendi konuşma sesini değiştirir. Kullanıcı 'sesini değiştir', 'kadın sesi', "
                     "'Kore sesiyle konuş' gibi bir şey derse çağır. Sesler: "
                     + "; ".join(f"{v} ({d})" for v, d in VOICE_INFO.items()) + ".",
                     _schema(ses=("STRING", "Ses adı, yukarıdaki listeden."))),
}


def _build_request(name: str, args: dict) -> str | None:
    """Özel aracın argümanlarını komut sisteminin anladığı cümleye çevirir (geçersizse None)."""
    def num(k):
        try:
            return max(0, min(100, int(float(args.get(k)))))
        except (TypeError, ValueError):
            return None

    def txt(k):
        return " ".join(str(args.get(k) or "").split())

    if name == "komut":
        return txt("istek") or None
    if name == "ses_ayarla":
        n = num("seviye")
        return None if n is None else f"ses seviyesini {n} yap"
    if name == "sessiz":
        d = txt("durum").lower()
        return "sessizi kaldır" if d.startswith(("ac", "aç", "kaldır")) else "sessize al"
    if name == "parlaklik_ayarla":
        n = num("seviye")
        return None if n is None else f"parlaklığı {n} yap"
    if name == "jarvis_kapat":
        return "Jarvis'i kapat"
    if name in ("uygulama_ac", "uygulama_kapat"):
        return f"{txt('ad')} {'aç' if name == 'uygulama_ac' else 'kapat'}" if txt("ad") else None
    if name == "medya":
        return _MEDIA.get(txt("eylem").lower())
    if name == "not_ekle":
        return f"not ekle {txt('metin')}" if txt("metin") else None
    if name == "gorev_ekle":
        return f"görev ekle: {txt('metin')}" if txt("metin") else None   # yer 'genel' ise normal görev listesi
    if name == "hatirlatma_ekle":
        return f"{txt('zaman')} {txt('metin')} diye hatırlat" if txt("metin") and txt("zaman") else None
    return None

