# İnceleme Takibi — 10 Ekim 2026

Bu kayıt, verilen statik inceleme listesini önceki v7 paketi ve bu devam çalışmasıyla karşılaştırır. “Düzeltildi” kaynak değişikliği ve belirtilen kontrollü test anlamındadır; gerçek Windows/Android/ses servisi doğrulaması değildir. GitHub'a yüklenmedi. Önceki paket değişikliklerinin ayrıntıları dağıtım ZIP'indeki ONCEKI_PAKET_NOTLARI.md içindedir.

## Bu Devam Çalışmasında Düzeltilenler

| Bulgu | Değişiklik / Kanıt | Sınır |
| --- | --- | --- |
| Android Goals eski ekran kaydı yeni ilerlemeyi ezebilir | Dosya yolu başına ortak, zayıf referanslı Goals nesnesi; miktar işlemleri aynı nesnenin kilidinde. UUID hedef kimlikleri aynı milisaniyede çakışmaz. | Aynı uygulama süreci için; dışarıdan dosya düzenleme ve çok süreçli Android kullanımını kapsamaz. |
| Goals yazma hatasında asıl dosyayı silebilir | Android AtomicFile ile başlangıç/tamamlama/hata geri alma; eski dosyayı silerek yeniden adlandırma kaldırıldı. | JVM testinde AtomicFile/JSON taklit edildi; Android'in gerçek depolama davranışı cihazda denenmedi. |
| WakeService paylaşılan instance/HOLDS | Görünürlük için volatile ve yakalanmış servis referansı; WakeHolds senkronize; durdurma/yeniden açma ana iş parçacığına gönderilir, eski servis ve diğer duraklatma nedenleri kontrol edilir. | WakeHolds gerçek JVM'de eşzamanlı denendi. WakeService/Vosk yaşam döngüsü APK ve cihazda denenmedi. |
| Bildirimde son duyulan konuşma | Bildirim metninden transkript çıkarıldı, bildirim görünürlüğü PRIVATE oldu. | Gerçek kilit ekranı cihazda kontrol edilmedi. |
| Android anahtarının düz metin saklanması | KeyVault AES/GCM + AndroidKeyStore; kullanıcı kimliği AAD; eski kayıtların başarılı şifreleme sonrasında geçişi. Şifre çözme hatasında anahtar kullanılmaz, şifreli kayıt tercih değişikliğinde korunur. | Gerçek AndroidKeyStore sağlayıcısı denenmedi. JCE şifreleme, yeni IV, kullanıcı ayrımı, bozulma, geçiş, kayıt hatası ve eski kaydı koruma denendi. |
| Store ayrı örneklerde kullanıcı listesi yazımı | Ortak kilitle okuma/değiştirme/yazma; kayıt tamamlanmadan başarı sayılmaz. Arayüz kayıt hatasını gösterir. | SharedPreferences taklit edildi; Android commit/disk koşulları cihazda denenmedi. |
| PC Profile ayrı nesnelerde eski veri yazımı | Aynı dosya için ortak veri; mutasyon/sayaç adımları RLock altında. İki ayrı handle ile bilgi/tercih koruma ve eşzamanlı 80 bilgi/120 komut denendi. | Dışarıdan profil dosyası düzenlemeleri ve başka süreçlerle eşzamanlı yazma kapsanmaz. Tek kopya çalışma modeli korunur. |
| requests_state sınırsız sıcak kayıt/journal yazımı | Son 512 tamamlanmış/iptal edilmiş kimlik JSON ve RAM'de; eskiler indeksli SQLite kimlik arşivinde. Süresi dolmuş kuyruk işleri de iptale dönüşür. | Tam kimlik tekilleştirmesini korumak için arşiv diskte büyür; bu sıfır büyüme iddiası değildir. Yeni istekler eski arşivi baştan serileştirmez. Arşiv elle silinmemelidir. |
| Arşivleme sonrası iptal/tekrar gönderme güvenliği | Eski kimlik aynı kullanıcı için reddedilir; arşivlenmiş iptal isteği activate/check içinde çalışamaz. Disk hatasında RAM kaydı korunur, yeni kimlik yeniden denenebilir. Arşiv bozuksa iş başlatılmaz. | SQLite stdlib; yeni paket bağımlılığı yok. Aktif ve çeviriden kuyruğa dönen istekler normal süreleri içinde arşivlenmez. |
| PC ana sayfasında CSP yok | Yerel script/bağlantı, kapalı object/base/üst çerçeve, mevcut YouTube çerçevesi ve görsel/medya sınırları. HTTP başlığı gerçek yerel sunucuda denendi. | Mevcut dinamik arayüz için inline script/style izinleri kalır. HTTPS dış görseller izinlidir; aşağıdaki politika notuna bak. Tarayıcıda görsel QA yapılmadı. |
| Telefon ses kabul hatası testinde zaman yarışı | HTTP hata yanıtı geçici dosya temizliğinden sonra gönderilir. Testteki sabit 50 ms bekleme kaldırıldı. | Hata yanıtı/temizlik gerçek yerel HTTP ile; mikrofon/çeviri taklit edildi. |
| Unicode font yoksa PDF round trip testinin kırılması | Ortamda font yoksa yalnız font gerektiren devam atlanır; Word/Excel kontrolleri öncesinde yapılır. Eksik fontta mevcut çıktıyı koruma testi kalır. | Test atlama çalışan PDF iddiası değildir. Bu ortamda font bulundu ve PDF testi çalıştı. |
| Mobil tek Gemini worker tüm istekleri bekletir | GeminiWorkers iki worker, sekiz bekleyen iş; dolulukta açık hata, arayüz iş parçacığında ağ çalıştırma yok. | Bloklu iki işin bağımsız başlaması ve kuyruk sınırı JVM'de denendi; gerçek Gemini gecikmesi ölçülmedi. |
| Arayüz rehberinde eski test sayısı | Sabit tarih/sayı yerine paketin SON_TEST_SONUCU.txt dosyasına yönlendirme. | Test sonucu özelliğin gerçek cihazda çalıştığını kanıtlamaz. |

## Önceki Paketlerde Ele Alınan İnceleme Maddeleri

| Alan / Maddeler | Durum |
| --- | --- |
| launcher bağımlılık kontrolü süre sınırı ve marker UTF-8 | Önceki pakette düzeltildi; tam kontrol paketi yeniden çalıştırıldı. |
| config import sırasında legacy anahtar okuma/çözme hatası | Önceki pakette açılışın düşmesini önleyen, mevcut kaydı koruyan davranış var. |
| engine_queue/audio/live istek kimliği, “dur”, süre sınırı ve profil kilidi beklerken iptal | Önceki pakette ortak kayıt akışı; ilgili güvenlik testleri korunuyor. |
| requests_state register disk hatası ve activate bağlam temizliği | Önceki düzeltmeler korunuyor; arşiv testleri bunlarla birlikte çalışıyor. |
| engine_loop geçersiz ses dosyası temizliği, ölü take_over dalı/yanlış yorum, _safe_cmd | Önceki pakette ele alındı. |
| engine_commands ölü prefetch / llm.can_prefetch | Gerçekte uygulanmayan optimizasyon kaldırıldı; hızlandırma yapılmış gibi sunulmuyor. |
| Uzun intent dağıtıcısı, handoff özel yardımcılarına erişim | engine_intents ayrıldı, public yardımcılar kullanılıyor. |
| llm kullanıcı istemcisi/histories kilidi, yeni sohbet eski taslak yanıtı | Kilit/epoch ve public reset_history; eski taslak yanıtı yeni sohbete kaydetmeme koruması. |
| llm görüntü fallback yanlış global istemci, sabit PNG MIME, system redaction | Kullanıcı istemcisi ve gerçek görsel türü, maskeleme; ilgili kontrollü testler korunuyor. |
| smart_router anahtar okuma, beklenmeyen OpenRouter gövdesi, yetenek hatasında sağlayıcı cooldown | Önceki pakette ele alındı; görüntü yeteneği hatası metni engellemez. |
| llm status Ollama ağ isteği, gömme N tekil istek, assert ile hata | Kısa model listesi önbelleği, toplu embedding ve açık hata yolu. |
| web yeni sohbet bekleyen onayları, _histories doğrudan değişimi | Önceki pakette iptal/alan temizliği ve public history API. |
| web Hub event_log kilitsiz içerik taraması | Motor olay kimlikleriyle metadata; içerik eşleştirme taraması kaldırıldı. |
| Web token !=, ham POST hata metni, KEY_FILE okuma hatası | Önceki pakette sabit zamanlı kontrol ve güvenli hata davranışı. |
| Web büyük upload tek seferde RAM okuma | Parçalı yükleme, limit ve hata temizliği; kullanıcı dosyası korunur. |
| Web global model ayarı, model ölçümü/folder pick senkron bekleme | Kullanıcı modelleri ve sahipli, sınırlı arka plan iş havuzu. |
| Sampler sonsuz döngü / özel hava durumu alanı | Durdurma olayı ve public invalidate_weather. |
| nxapi DATA_DIR uyuşmazlığı, dosya önbelleği yarışı/tekrar sıralama, boş hedef, ölü learn_from_chat | Önceki pakette ele alındı. |
| phone bilinmeyen POST yanıtsız, sayaç yarışı, token dosyası her istek, cevap için log taraması | 404, kilit, dosya kimliği önbelleği ve rid tabanlı bekleme. |
| web_phone token_tail | Gereksiz token parçası kaldırıldı. |
| developer bozuk state/geçmiş/access JSON, proje tarama maliyeti | Savunmacı okuma ve sınırlı dosya/içerik önbelleği; gerçek uygulama hash kontrolü ham dosyadan. |
| task_agents resume adım sonucu yazılmaması | Adım başlangıcı ve sonucu kalıcılaştırılır; kesinti senaryosu testi var. |
| study PDF timeout ardından sınırsız inline okuma | Timeout inline fallback'e dönmez; kontrollü testi var. |
| updater resmi güncellemede korunan altyapı dosyaları | Resmi güncelleme yetkisi geliştirme taslağından ayrı; test ve rollback korunur. |
| personalization hatırlatması save hatasında atlanır | Başarısız kayıtta yeniden deneme; mevcut test korunur. |
| studyexam bank tekrar okuma, mock yeniden bulma, parse tekilleştirme | İşlem başına ortak bank snapshot'ı; mevcut veriyle mock çıktısı ve set tabanlı tekilleştirme. |
| study soru embedding tekrarları / analyze bank yeniden kurma | Sınırlı, kullanıcı/sağlayıcı/ayar kimlikli soru embedding önbelleği; işlem bank paylaşımı. |
| voice aynı cevapta varsayılan sese fallback | Seçilen ses korunur; servis hata mesajı; sonraki parçada ses değiştirme yok. Gerçek cihaz nedeni kesinleştirilmedi. |
| Live ham ses diske yazımı, maskesiz araç argümanları, SDK model_fields | Ses kaydı varsayılan kapalı, araç mesajları force redact, savunmacı SDK alan erişimi. |
| Büyük Live ve Bridge | Live ses pipeline/transkript/araç/oturum modülleri; web modeller/görevler/ses/entegrasyon köprüleri ayrıldı. Koordinatörler hâlâ büyük; tam modülerlik iddiası yok. |

## Doğrulanmayan İddialar, Korunan Tercihler Ve Açık Borçlar

| Madde | Sonuç / Yapılacak |
| --- | --- |
| requests_state ve history örnek başına kilit kullanıyor iddiası | Güncel Python modüllerinde global RLock var. Bu iddia bu iki modül için doğru değil. Profile eski snapshot sorunu ayrı olarak düzeltildi. |
| learning RLock'a gizli bağımlılık | Yeniden giriş kasıtlı; kilit sözleşmesi belirtildi. Sırf RLock kullanılması hata değildir; Lock'a çevrilmedi. |
| MutationObserver her mutasyonda tüm body'yi tarar | Güncel kod eklenen düğüm ve değişen metni işler. İddia bu biçimde doğrulanmadı; ölçüm olmadan yeniden yazılmadı. |
| Live asyncio sleep meşgul bekleme/CPU darboğazı | Beklemeler event loop'a kontrol verir. Ses/CPU profili olmadan kesin darboğaz sayılmadı; zamanlama yeniden yazılmadı. |
| Android kurulum QR'ında ham API anahtarı | **Kaynakta düzeltildi (v9).** QR v2 yalnız HTTPS adresi ve 90 saniyelik tek kullanımlık kod taşır. Sunucu kodu atomik tüketir, güncel kullanıcı anahtarını o anda alır; anahtarı grant tablosuna kaydetmez. Yeni QR eski APK ile uyumlu değildir; Android 3.0.8 APK/cihaz doğrulaması hâlâ gerekir. |
| Windows dışı privacy.protect b64, YouTube/legacy anahtar politikası farkı | **Açık platform politikası.** b64 şifreleme değildir. Windows DPAPI testi Linux'ta çalıştırılmadı; Windows dışı dağıtım güvenli anahtar deposu olarak sunulmamalıdır. |
| Dış HTTPS görsel/thumbnail yüklemesi | Mevcut web görsel işlevi nedeniyle CSP'de izinli. Dış sunucu tarayıcının ağ bilgilerini görebilir. Gizlilik için yalnız yerel görüntü politikası veya denetimli proxy ayrıca tasarlanmalıdır; tam gizlilik sağlandı denmiyor. |
| main import anında EngineContext/threads | **Düzeltildi (v9).** Motor ilk gerçek erişimde, kilit altında bir kez oluşturulur. Import-only ve 16 eşzamanlı erişim denemesi; mevcut facade/CLI entegrasyonları geçti. Web motor alanlarını istediğinde normal başlangıç yine yapılır; gerçek açılış saniyesi ölçülmedi. |
| main facade __class__, _exported; runtime dinamik bağımlılık listesi | _exported için public is_exported sözleşmesi eklendi. __class__ facade tekniği/dinamik bağlama uyumluluk için tutulur; kanıtlanmış kırılma yok. |
| router sınıflandırma + cevap seri LLM çağrıları | Mimari maliyet; mevcut deterministik yollar korunur. Ölü prefetch temizliği gerçek hızlandırma değildir. Gecikme ölçümü gerekir. |
| Live paylaşılan transkript durumu, dev sınıfların kalan bölümleri, private API'ler | Modül ayrımları yapıldı, fakat tüm alanlara yeni kilit eklenmedi. Yarış tekrarı ve sıra/oturum sınırı testleriyle sonraki bakım işi. |
| Ses önizlemesinin seçim kaydetmesi | Mevcut PC akışı seç ve dinle davranışıdır; bilinçli tercih. Android ses seçimi yalnız Tamam sonrası kaydeder. |
| auto_apply=False eski durum alanı | Eski kayıtların otomatik uygulamayı açmasını engelleyen uyumluluk koruması; güvenlik için tutuldu. |
| defusedxml, fsync/dizin fsync, shutdown son wait, daemon timer, ayrı Handler/MainActivity/nx.js, deprecated onActivityResult | Bakım/sağlamlaştırma adayları; her biri kanıtlanmış kullanıcı hatası olarak sunulmadı. Daha büyük değişiklik veya cihaz testi gerektirir. |
| Kullanıcı adı regex lastindex/startswith, medya durdur fast path, kamera snapshot ömrü, _run_steps audit | Verilen statik olasılıklar; güncel akışta kesin yanlış yan etki üretildiği gösterilmedi. Rastgele davranış değişikliği yapılmadı. |
| “Seçili alanı anlat” / “Seçimi kaldır” | Kullanıcı bildirimi geri çekildi; bu düğmelere hata düzeltmesi yapılmadı. |

## Doğrulama Sınırı

Sonuç sayısı ve tam çıktı ZIP'in SON_TEST_SONUCU.txt dosyasındadır. Python testleri, JavaScript sözdizimi, 10 JavaScript davranış grubu ve 6 Python entegrasyonu çalıştırılır. Android ek kontrolü gerçek Goals/User/Store/KeyVault/GeminiWorkers/Gemini kaynaklarını Java 17 ile derler; Android/JSON/Handler/SharedPreferences test karşılıkları kullanır. Goals, WakeHolds, KeyVault/Store ve GeminiWorkers davranış harness'leri JVM'de çalışır. Bu APK derlemesi veya gerçek AndroidKeyStore/Vosk/telefon kontrolü değildir. MainActivity/WakeService tam Android derlemesi yapılmadı.

Windows gerçek DPAPI, mikrofon/TTS/kamera, Gemini Live ağı ve Android/iPhone cihaz kontrolleri açık kalır. Yeni kaynakların mevcut APK'ya kendiliğinden uygulanacağı iddia edilmez. Bu dosya “sistemde başka hata yok” raporu değildir.

Android Keystore tasarımı için birincil kaynak: https://developer.android.com/privacy-and-security/keystore ve https://developer.android.com/reference/android/security/keystore/KeyGenParameterSpec .

## v9 — Güvenli Kurulum Ve Kapanış Devamı

- PC QR v2, /api/android-setup ve AndroidSetup birlikte değiştirildi. Normal HTTPS sertifika doğrulaması kullanılır; TLS doğrulamasını kapatma yok, redirect yok. İstemci yalnız HTTPS `.ts.net`, 443 ve sabit endpoint kabul eder; kod URL parametresine yazılmaz.
- Sunucu kurulum endpointi yalnız loopback proxy üzerinden erişilir. Host izin listesi ve tarayıcı Origin reddi, kısa gövde sınırı, başarısız deneme limiti ve no-store yanıtı vardır. LAN/Tailscale doğrudan düz HTTP kurulum yolu yoktur. Tailscale Serve HTTPS yoksa anahtarlı QR'a geri dönülmez.
- Kodun tek kullanımı/eşzamanlı tüketimi, süresi, yeni QR'ın eskisini iptal etmesi, kayıt silme/anahtar yokluğu, sunucu kapanışında iptal, anahtarsız QR ve gerçek yerel HTTP kabul/reddetme test edildi. Bu test gerçek TLS/Tailscale telefonu değildir.
- Smart Router anahtar çözme istisnası sağlayıcı hazır oluşunu düşürür; başka metin sağlayıcısını bloke etmez.
- Gecikmeli web kapanış/yeniden başlatma ve motor bildirimleri daemon timer kullanır. Bekleyen 30 saniyelik bildirim varken alt sürecin 3 saniyelik test sınırı içinde kapanması doğrulandı. Launcher kill sonrası son wait de sınırlı.
- Android kaynak sürümü 3.0.8 / versionCode 22. APK mevcut pakete eklenmedi.

**APK engeli fiilen denendi:** `bash gradlew --offline assembleDebug`, Gradle 8.14.3 dağıtımı yerelde olmadığı için `services.gradle.org` adresinden indirmeye çalıştı; `Network is unreachable` ile durdu. Android SDK (`android.jar`, sdkmanager) ve bağlı/erişilebilir Android cihazı bulunmadı. Bu yüzden tam APK, Vosk/mikrofon yaşam döngüsü ve gerçek AndroidKeyStore kontrolü tamamlandı sayılmıyor. Windows PC ve iPhone da bu yürütme ortamına bağlı değil.

Doğrulanmamış performans iddiaları ve korunan platform tercihleri hata kapatılmış gibi gösterilmedi. Bütün büyük sınıfları sırf satır sayısı için yeniden yazmak bu düzeltmenin doğrulanmış kapsamı değildir.

Ek kontrol: JDK parser ile Android kaynak ağacındaki bütün Java dosyalarının sözdizimi denetlenir; MainActivity ve WakeService de kapsanır. Bu işlem SDK sembol çözümlemesi, APK üretimi veya cihaz testi değildir.
