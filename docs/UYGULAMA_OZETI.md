> Güncel sürüm: Geliştirme Atölyesi kaldırılmıştır. Aşağıdaki eski sürüm incelemeleri tarihsel kayıttır.

# Uygulama özeti — 6 Ekim 2026

## Baz alınan sürüm

Bu paketin güncel tabanı, 6 Ekim 2026 saat 10:32'de oluşturulan `JARVIS-main-Git-Calisma-Guncel.zip` dosyasıdır. İlk yüklenen `Jarvis-main.zip` sonrasındaki Çalışma/Git değişiklikleri korunarak aşağıdaki düzeltmeler birleştirildi.

## Uygulanan değişiklikler

### Çökme ve çeviri

- Ana ekranı durduran başlatma hatası giderildi; not kartı ve diğer sayfalar yeniden çiziliyor.
- “Metni çevir” komutu çeviriyi doğrudan sohbet balonunda gösteriyor.
- Özetleme sonrasında gelen çeviri isteği, önceki özgün metni kullanıyor.
- Sohbette hem “Türkçeye Çevir” hem “İngilizceye Çevir” hızlı düğmeleri bulunuyor.


| Bölüm | Sonuç |
| --- | --- |
| Çalışma | Güncel tabandaki dönem/oturum, son 3 yıl, Bugünkü Çalışmayı Başlat, Yanlışlarım, Deneme, konu kilidi ve PDF sayfa kaynakları korundu. |
| GitHub | GitHub'a Yükle ve GitHub'dan Al yönleri, uzak sürüm kontrolü ve yerel kaynak koruması korundu. |
| Self-Coder: metin eşleşmesi | Logdaki `find metni 0 kez bulundu` hatası için, geçersiz planın ardından mevcut kaynakla yalnız bir kez yeni plan istenir. İkinci plan da geçersizse durur. Hazırlık sırasında kaynak değiştirilmez. |
| Self-Coder: sayı içeren komutlar | `ses seviyesini 20 yap` artık ikinci geliştirme önerisini seçmez. Öneri seçimi açık bir geliştirme/öneri komutu veya `2 uygula` gibi bağımsız bir seçim gerektirir. |
| Self-Coder: bekleyen plan | `bu kod ne yapacak` planın amacını, dosyalarını ve riskini açıklar. Ses ve diğer bağımsız komutlar normal işlenir; plan korunur. Uygulama ve iptal ifadeleri ayrıca tanınır. |
| Telefon eşleştirme | PC bağlantı QR'ı kullanıcıya özel, 90 saniyelik ve tek kullanımlık kod taşır. Kod, kişisel telefon erişim belirtecine dönüştürülür. QR yenileme ve gerçek bağlantı durumu eklendi. |
| Android/iPhone web uygulaması | Ana ekrana kurulum, ikonlar ve çevrimdışı bağlantı yardım ekranı eklendi. Çevrimdışıyken PC işlemleri çalışmaz. Mesajlar ve API anahtarları service worker önbelleğine alınmaz. |
| Telefon mikrofonu | Sekme gizlendiğinde kayıt durdurulur; iptal edilen konuşma gönderilmez. Gecikmiş izin yanıtı ve çift tıklama korunur. Gönderim hatasında yazılan mesaj korunur. |
| Bağımsız Android istemci | Kaynak sürümü 3.0.8. TTS kuyruğunda yalnız son geçerli konuşma parçası tamamlanınca dinleme geri açılır; eski/tekrarlı tamamlanma bildirimleri yeni turu etkilemez. |
| İlk açılış | Global API anahtarı penceresi kaldırıldı. Anahtar, aktif kullanıcının Ayarlar ekranından eklenir. |
| Windows başlatma/kurulum | Başlatma hata kodu korunur. Kilitli bağımlılık kurulumu başarısızsa temiz bir geçici ortamda alternatif kurulum denenir. |

## Kullanım

1. ZIP'i ayrı bir klasöre çıkar. Kendi kullanıcı verilerini ve API anahtarlarını koru; bu paket kişisel verilerini içermez.
2. Windows'ta ilk kurulum için `kurulum.bat`, ardından `baslat.bat` kullan.
3. PC bağlantılı telefon erişimi için Araçlar > Telefon ekranından erişimi aç, kullanıcıyı seç ve QR'ı telefon kamerasıyla okut. QR süresi dolarsa yenile.
4. Kurulum ve mikrofon için telefonun PC'ye erişebildiği Tailscale HTTPS adresini kullan. Android'de kurulum düğmesini, iPhone'da Paylaş > Ana Ekrana Ekle seçeneğini kullan. PC'de Jarvis açık kalmalıdır.
5. Bağımsız Android uygulaması kendi Gemini anahtarıyla çalışır. Bu seçenek PC bağlantılı web uygulamasından ayrıdır. Anahtar QR'ının ekrandan kaldırılması API anahtarını iptal etmez.

Self-Coder planı hazırlamak için `kendine yeni özellik ekle: ...`, planı anlamak için `planı açıkla` denebilir. Kaynak değişikliği için `uygula`; yüksek riskte `yüksek riski onaylıyorum` gerekir. Uygulamanın kendi onay, yedek, test ve geri alma akışı korunur. GitHub'a otomatik gönderim yapılmaz.

## Doğrulama ve sınırlar

- Python regresyonları: pytest ile **79 başarılı, 1 atlanan test ve 10 başarılı alt kontrol**. Aynı testler uygulamanın kullandığı unittest komutuyla **80 test, 1 atlama, başarı** verdi.
- Atlanan kontrol, Gemini Live içe aktarımında test ortamının sahte Google SDK'sında `Schema` bulunmadığı için çalışmadı. Bu sonuç canlı ses oturumunun doğrulandığı anlamına gelmez.
- Çalışma'nın asenkron belge ekleme ve soru bankası testleri ayrıca bağımsız çalıştırıldı: **3 başarılı**. SDK'sız test hazırlığındaki çalıştırılma sırasına bağımlılık düzeltildi.
- **79 Python dosyası** bytecode yazmadan derlendi; JavaScript sözdizimi kontrolleri geçti. Birleştirme çatışması işareti bulunmadı.
- Mobil JavaScript; QR, kullanıcı profili, başarısız/başarılı gönderim, gizlenince mikrofon iptali ve iPhone kurulum açıklaması için **taklit DOM ortamında** sınandı. Gerçek tarayıcı testi yapılmadı.
- Android konuşma kuyruğu: **11 Java kontrolü başarılı**. Gerçek `Speaker.java` için **8 taklit Android TTS entegrasyon kontrolü başarılı**. Android SDK veya cihaz testi yerine geçmez.

Tekrarlamak için: `python -m unittest discover -s tests -q`, `node tests/mobile_behavior.js`. Node yalnız mobil JavaScript doğrulaması içindir; Jarvis'i başlatmak için gerekmez. Java kuyruğu kontrolü `SpeechQueue.java` ve `android/Jarvis3/tests/SpeechQueueCheck.java` derlenerek çalıştırılabilir.

Bu ortam Linux'tur. Windows BAT akışı, gerçek Android TTS/mikrofon, iPhone kurulumu, kamera/QR ve canlı Gemini bağlantısı gerçek cihazlarda sınanmadı. Android APK derlenmedi; paket Android kaynaklarını içerir. iPhone erişimi ortak web uygulaması üzerinden sağlanır; native iOS uygulaması üretilmedi.

API anahtarı olmadan arayüz açılır; bulut modelini kullanmak için kullanıcı kendi anahtarını eklemelidir. Offline STT/TTS için yeni bir motor kurulmadı; mevcut Ollama ve gizlilik davranışı korunur.

## 6 Ekim — kamera, çalışma ve planlama güncellemesi

- Kamera/ekran paylaşımı mevcut görüntü akışını Ekran sayfasında görünür önizlemeye dönüştürür. Sesle kamera açılınca bu sayfa açılır. Kamera kapatma düğmesi bulunur; görüntü alınamazsa açıklama gösterilir.
- Çalışma sayfasında yüklenen kaynak seçilir. Metin alanı boşken Çalışmaya Başla, seçili kaynağın metniyle anlatım ve sorular hazırlar. Son yüklenen dosya varsayılan seçilir. Sonraki sorular da seçili kaynakla yanıtlanır.
- Seçili kaynağın başlığı ve gerçek metin kesitlerinden soru önerileri gösterilir. Öneriye basınca çalıştırılır. Bu öneriler çıkmış sınav sorusu olarak işaretlenmez; kaynak temelli çalışma sorularıdır.
- Veri Klasörü, Ayarlar/Güvenlik ekranından Araçlar'a taşındı.
- Araçlar'da Takvim ve Görevler birleşti: aylık takvim, ay değiştirme, Bugün düğmesi, gün seçimi, o günün etkinlik/görevleri ve notlar aynı ekrandadır. Etkinlik için tarih/saat seçilebilir veya Türkçe gün ifadesi yazılabilir. Göreve tarih eklenebilir; eski tarihsiz görevler korunur. Tarihli görevler takvimde görünür; etkinliklerin mevcut hatırlatma sistemi korunur.
- Ana sayfada Notlarım kartı, mevcut notlar ve yeni not ekleme düğmesi bulunur.
- Yeni kaynak/görev davranışları Python ile; boş konu, gün/ay seçimi, birleşik ekran ve PNG kamera önizlemesi `node tests/desktop_flows.js` ile taklit DOM ortamında doğrulandı. Gerçek Windows kamera testi bu ortamda yapılamadı.

Kurulum: Jarvis'i kapat. ZIP içindeki `Jarvis-main` klasörünün içeriğini, kullandığın `jarvis V5` klasörünün içine kopyala ve aynı adlı kaynak dosyalarını değiştir. `baslat.bat` ile aç. `baslat.bat` ilk satırı `@echo off` olmalıdır; dosyanın içine `cmd` eklenmez.
