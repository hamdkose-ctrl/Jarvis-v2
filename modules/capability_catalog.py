"""Yetenek kataloğu: Jarvis'in gerçekten yapabildiklerinin listesi.

Neden: kelime kalıpları yalnız "ezberlenmiş" cümlelerde çalışıyor; serbest konuşan
kullanıcı aynı işi 10 farklı şekilde söyleyebiliyor. Bu dosya, becerileri **tek
yerde ve insan dilinde** tanımlar; beyni (`capability_brain`) buradan eşleştirir.

Her yetenek:
- `intent`: bilinen niyet adı (engine_intents'te karşılığı var)
- `does`: tek cümle, ne yapar
- `needs`: sırayla gereken bilgiler (`window`, `target`, `text`, `query`, `name`)
- `examples`: kullanıcının gerçekten söyleyebileceği cümleler
- `phrases`: eşleşmeyi güçlendiren anahtar sözcükler
"""
from __future__ import annotations

CATALOG: tuple[dict, ...] = (
    {"intent": "pc_type", "does": "bir uygulamanın metin alanına (tarayıcıda adres çubuğuna) yazı yazar",
     "needs": ("window", "text"),
     "phrases": ("yaz", "yaziver", "gir", "adres", "arama", "kutu", "alan"),
     "examples": ("chrome da adres alanına youtube yaz", "not defterine merhaba yaz",
                  "adres çubuğuna hava durumu yaz", "arama kutusuna telefon yaz")},
    {"intent": "pc_open_site", "does": "tarayıcıda bir siteyi/hizmeti açar (adres çubuğuna yazıp Enter)",
     "needs": ("text",),
     "phrases": ("aç", "açsana", "site", "youtube", "mail", "gmail", "müzik", "google"),
     "examples": ("youtube aç", "maili aç", "müzik aç", "gmail açsana", "google aç")},
    {"intent": "screen_read_text", "does": "ekrandaki yazıyı okur (sayfa, mail listesi, belge)",
     "needs": (),
     "phrases": ("ne yazıyor", "ne yazmış", "mail", "yazı", "oku", "ne var"),
     "examples": ("ilk mail ne", "ekranda ne yazıyor", "sayfada ne yazıyor")},
    {"intent": "pc_search", "does": "yazılanı çalıştırır: aramayı başlatır, Enter'a basar",
     "needs": ("window",),
     "phrases": ("enter", "ara", "ara bakalım", "başlat", "git", "yönlendir"),
     "examples": ("chrome da enter", "aramayı başlat", "youtube'a git", "ara bakalım")},
    {"intent": "pc_click_result", "does": "ekrandaki bir yazıya/bağlantıya tıklar",
     "needs": ("query",),
     "phrases": ("sonuç", "sonucuna", "tıkla", "bas", "linke", "başlığa", "gir"),
     "examples": ("youtube sonucuna tıkla", "ilk sonuca bas", "ekrandaki haberler yazısına tıkla")},
    {"intent": "pc_click", "does": "bir penceredeki düğmeye/öğeye basar",
     "needs": ("window", "target"),
     "phrases": ("düğme", "düğmesine", "tıkla", "bas", "kaydet", "kapat", "tamam"),
     "examples": ("not defterinde kaydet düğmesine bas", "chrome'da kapat düğmesine bas")},
    {"intent": "pc_save", "does": "açık belgeyi kaydeder (yalnız deneme klasörüne, onayla)",
     "needs": ("window", "name"),
     "phrases": ("kaydet", "sakla", "dosya", "adıyla"),
     "examples": ("not defterini toplanti adıyla kaydet", "bunu kaydet")},
    {"intent": "pc_confirm", "does": "onay bekleyen riskli işlemi yürütür",
     "needs": (),
     "phrases": ("onay", "onaylıyorum", "evet", "tamam yap", "devam"),
     "examples": ("onaylıyorum", "evet onayla", "tamam devam et")},
    {"intent": "screen_summary", "does": "ekranda ne olduğunu söyler (öndeki pencere, açık programlar)",
     "needs": (),
     "phrases": ("ekran", "ekranda", "açık", "pencere", "ne var", "üstünde"),
     "examples": ("ekranda ne var", "hangi program açık", "ne üstünde çalışıyorum")},
    {"intent": "screen_controls", "does": "bir penceredeki düğme ve alanları listeler",
     "needs": ("window",),
     "phrases": ("ne var", "düğmeler", "alanlar", "içinde", "penceresinde"),
     "examples": ("chrome'da ne var", "not defterinde hangi düğmeler var")},
    {"intent": "file_list", "does": "bir klasördeki dosyaları listeler",
     "needs": ("path",),
     "phrases": ("klasör", "dosya", "listele", "içinde ne var"),
     "examples": ("indirilenler klasöründe ne var", "masaüstündeki dosyaları listele")},
    {"intent": "file_read", "does": "bir dosyanın içeriğini okur",
     "needs": ("path",),
     "phrases": ("oku", "içeriği", "dosyayı"),
     "examples": ("gece planı dosyasını oku", "bu dosyayı oku")},
    {"intent": "autonomy_schedule", "does": "bir işi ileri bir saate kurar",
     "needs": ("phrase",),
     "phrases": ("yarın", "saat", "sonra", "kuyruk", "kur"),
     "examples": ("yarın 09:00'da not defterinde kaydet düğmesine bas", "5 dakika sonra chrome da enter")},
    {"intent": "autonomy_status", "does": "otonomi kuyruğunun durumunu söyler",
     "needs": (),
     "phrases": ("otonomi", "kuyruk", "durum"),
     "examples": ("otonomi durumu", "kuyrukta ne var")},
)


def by_intent(intent: str) -> dict | None:
    return next((item for item in CATALOG if item["intent"] == intent), None)


def examples_text() -> str:
    """Kullanıcıya 'şunları yapabilirim' demek için kısa liste."""
    return "; ".join(f"{item['intent']}: {item['examples'][0]}" for item in CATALOG)
