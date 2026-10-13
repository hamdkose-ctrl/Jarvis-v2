Son paket: [bağımsız matematik denetimi, test edilmiş güncelleme ve kalan gerçek PC doğrulaması](docs/KALAN_ISLER_20261008.md).

Güvenli geliştirme güncellemesi: [ayrı kopyada test, açılış kurtarma ve yedek sınırları](docs/GUVENLI_GELISTIRME_20261008.md).

İsteğe bağlı OpenAI/Claude desteği ve temizlik: [kurulum ve kullanım](docs/YAPAY_ZEKA_SAGLAYICILARI.md).

Sesli işlem ve PC pencere kontrolü güncellemesi: [kullanım ve kurulum](docs/SESLI_ISLEMLER.md).

# Güncel değişiklik

Şifreli, sohbet üzerinden çalışan geliştirme modu eklendi. Görsel/dosya referansı, kalıcı taslak ve konuşma bağlamı, açık kullanıcı onayı, test ve geri alma içerir. Kullanım: [GELISTIRME_MODU](docs/GELISTIRME_MODU.md). Eski kurulumun üzerine kopyalayıp `baslat.bat` ile açın.

# JARVIS V5 — Tek Ana Kod / Çoklu Kullanıcı

Main ayrıştırması: [42 satırlık giriş, 9 iş modülü ve ortak çalışma bağlamı](docs/MAIN_MODULER_20261009.md).

Modül içi inceleme: [ses kuyruğu, kapanış ve pano düzeltmeleri](docs/MODUL_KONTROLU_20261009.md).

Modül dış bağlantıları: [web/telefon, istek kimliği ve tek motor bağlantısı](docs/DIS_BAGLANTI_KONTROLU_20261009.md).

Modüller arası kontrol: [çağrı bağları, eşzamanlı istek durumu ve toplu sesli sonuç](docs/MODULLER_ARASI_KONTROL_20261009.md).

Genel inceleme: [çalışma, dosyalar, hafıza/görevler, geliştirme ve arayüz](docs/KALAN_INCELEMELER_20261009.md).

Son genel kontrol: [arayüz isteği sahipliği ve kuyruk hata sonuçları](docs/GENEL_KONTROL_20261009.md).

Bu depo Ev ve İş bilgisayarında çalışan **aynı JARVIS kod tabanının** ana geliştirme kaynağıdır. İki ayrı JARVIS sürümü yürütülmez.

## 6 Ekim 2026 güncel paket

- Çalışma: son 3 yıl, dönem/oturum, Yanlışlarım, Deneme, konu kilidi, PDF sayfa kaynakları.
- Telefon: Android ve iPhone’da ortak mobil web uygulaması. Araçlar > Telefon’dan erişimi aç, kullanıcını seç ve telefon kamerasıyla QR’ı okut. Ana ekrana kurulum ve mikrofon için Tailscale HTTPS adresini kullan. PC’de Jarvis açık kalmalı.
- Android bağımsız istemci: kaynak sürümü 3.0.8. Kendi Gemini anahtarıyla PC kapalıyken de çalışır; bu pakette derlenmiş APK bulunmaz.
- İlk açılışta global API anahtarı sorulmaz; anahtar aktif kullanıcı profilinin Ayarlar ekranından eklenir.

## GitHub akışı
- `main` tek ana sürümdür; Ev veya İş PC fark etmez.
- Kullanıcı `git yükle`, `GitHub'a yükle` veya `GitHub'a gönder` dediğinde **ya da Ayarlar > Bağlantılar > GitHub'a Yükle düğmesine bastığında** regresyon testleri yeniden çalışır ve yerel kaynak farkları `main` dalına gönderilir.
- Uzak `main` bu PC'nin kayıtlı tabanından ilerideyse yayın durur; force-push yapılmaz. Önce kontrollü güncelleme gerekir.
- Güncelleme ancak kullanıcı açıkça `güncellemeyi kur / kendini güncelle` dediğinde uygulanır.

## Kullanıcı ve API anahtarları
- Her kullanıcı ayrı profil, hafıza, çalışma verisi ve API anahtarlarına sahiptir.
- Gemini ve Groq anahtarları kullanıcılar arasında paylaşılmaz ve başka kullanıcıya fallback yapılmaz.
- Ayarlar > Bağlantılar ekranındaki durum aktif kullanıcıyı gösterir.

## Bakım ve testler

Dokümanlar `docs/`, işlem scriptleri `scripts/` altındadır. Kök dizindeki başlatıcılar kullanım için korunmuştur. Ayrı atölye kaldırma BAT’ı yoktur; `baslat.bat` içindeki kurulum temizliği eski kopyasını da siler. Test yönergesi: [TESTLER](docs/TESTLER.md). Yedekler `.backups/` altında tutulur ve yayınlanmaz.


## Smart Router ve görev ajanları

Ücretsiz havuz, görev planı, gerçek Playwright tarayıcı işlemleri ve PC/ses tanılama için [kullanım ve kurulum](docs/SMART_ROUTER_AJANLAR.md). Mevcut geliştirme modu, görselleri ve geri alma korunur.

Son inceleme ve düzeltmeler: [Genel kontrol · 7 Ekim 2026](docs/GENEL_KONTROL_20261007.md).

Çalışma bölümü incelemesi ve düzeltmeler: [Çalışma kontrolü](docs/CALISMA_KONTROL_20261007.md).

Tek kopya kontrolü: [davranış, testler ve kurulum](docs/TEK_KOPYA_20261009.md).
