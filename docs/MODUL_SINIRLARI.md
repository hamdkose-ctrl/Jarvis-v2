# Modül Sınırları — 10 Ekim 2026

Bu bölüm son kaynak paketindeki ayrımı anlatır. Kodun ayrılması tek başına cihazdaki ses sorunlarının çözüldüğünü veya açılışın hızlandığını göstermez.

| Modül | Sorumluluk | Sınır |
|---|---|---|
| `main.py` | Mevcut motor bağlamına uyum cephesi ve giriş | Başlangıçta bağlam kurma davranışı korunur. |
| `modules/engine_commands.py` | Hızlı komutlar, bekleyen konuşma/onay, yönlendirme sonucu hazırlama | Modelin sınıflandırdığı işin yürütmesini `engine_intents.dispatch()` çağrısına bırakır. |
| `modules/engine_intents.py` | Sınıflandırılmış belge, uygulama, sistem, not, ekran ve sohbet işleri | Yeni kullanıcı veya istek kimliği üretmez; çağıranın `runtime` nesnesini kullanır. İşlem girişinde iptal kontrolü yapar. |
| `web.py` / `Bridge` | HTTP/SSE, pencere, genel durum ve köprü bileşimi | Taşınan API metotları aynı ad ve parametrelerle miras alınır. |
| `web_models.py` | Kullanıcı/model anahtarları, sağlayıcı seçimleri, model durumu ve açık ölçüm | `self._runtime` üzerinden bağımlılıklara erişir. Anahtarı yalnız kaydetmek model denemesi başlatmaz; açık doğrulama/ölçüm çağrıları model isteği yapabilir. |
| `web_integrations.py` | Google OAuth, ev/iş görev bağlantısı ve ntfy | Verilen köprü bağlamını kullanır; kullanıcı tercihlerinin sahibi korunur. |
| `modules/live_tools.py` | Sabit araç şemaları, ses isimleri, kanonik komut dönüşümü | Mikrofon veya Live oturumu yönetmez. Komut dönüştürmek komutu çalıştırmak değildir. |
| `modules/live.py` | Mikrofon/oturum ve canlı bileşenlerin bağlanması | `live_tools` sabitlerini eski isimlerle yeniden sunar. Doğrudan araçların kayıt/iptal/kullanıcı sınırı korunur. |

## Canlı Araç ve Transkript Bileşenleri

`live_tool_runner.py` araç yürütmesini, kayıtlı doğrudan çağrıyı ve ses geçişi hazırlığını taşır. `live_transcripts.py` kullanıcı/assistant metinlerini biriktiren alanları arayüze aktarır. İkisi de mevcut Live nesnesini ve servis adaptörlerini alır; ikinci bir oturum veya ayrı kullanıcı/istek kimliği üretmez. Eski `Live._run_tool()`, `_direct_tool()`, `_change_voice()`, `_flush_user()` ve `_flush_transcripts()` girişleri ince delegeler olarak korunur. Paylaşılan oturum durumu hâlâ Live nesnesindedir; bu taşıma tüm ses yaşam döngüsünün yeniden tasarlandığı anlamına gelmez.

Ek gizlilik düzeltmesi: 32 karakterlik hexadecimal uygulama kimliğinin içindeki telefon-benzeri rakam dizisi kimliği bozmaz. Ayrı telefon numaraları ve bilinen API anahtarları maskeleme kurallarına tabi kalır. Herhangi bir metnin tüm hassas verilerini saptama garantisi değildir.

## Açık Erişim Metotları

- `llm.gemini_client()` mevcut kullanıcı bağlamının istemcisini verir; başka kişinin anahtarına fallback eklemez.
- `llm.provider_configuration()` durum tüketicileri için sağlayıcı ayarının kopyasını verir.
- `llm.test_groq()` açıkça istenen bağlantı denemesidir; gerçek çağrı yapar.
- `handoff.due()` ve `handoff.explain_error()` ses/komut işleyicilerinin açık girişleridir. Eski iç fonksiyonlar uyum için korunur.
- `Sampler.invalidate_weather()` şehir tercihi değişince hava önbelleğinin yenilenmesini ister.

## Kontrol Sınırı

Taşınmadan önceki Bridge metotlarının adları ve parametreleri karşılaştırıldı. Tam Python/JavaScript/entegrasyon paketi ve ek kullanıcı ayrımı, belge-sohbet sürekliliği, iptal denemeleri kullanıldı. OS, ses ve model servisleri denemelerde taklit edilir; Windows/Android/iPhone cihaz doğrulaması değildir.

`Bridge` hâlâ HTTP/durum/pencere bileşimini taşır; `Live` oturum ve ses yaşam döngüsünü birlikte yönetir. Bu ayrım bütün büyük sınıfların bitirildiği anlamına gelmez. Android v1 kurulum QR'ında ham anahtar aktarımı sürer; güncel Android istemcisi ve APK ile birlikte protokol değişikliği gerekir.

## Mikrofon Bileşeni

`modules/live_microphone.py` mikrofon stream okumasını, kare biriktirmeyi, kazanç hesabını, uyanmayı ve yankı korumasını taşır. Eski `Live._mic_loop()`, `_agc()` ve `_on_frame()` metotları aynı nesneye delege eder. Mikrofon kapanınca stream bırakma, kazanç tavanı, iki güçlü uyanma karesi ve hoparlör sonrası yankı aralığı korunur. Bu taşıma yeni STT modeli veya ses tanıma ayarı eklemez.

Bu aşamada 6 yapay ses/cihaz testi eklenmiştir; gerçek Windows mikrofon gecikmesi, algılama doğruluğu ve ses aygıtı yaşam döngüsü cihazda doğrulanmamıştır. Oturum yönetimi ve durum alanları hâlâ Live içinde bulunur.

## Oturum Bileşenleri

`live_session_config.py` STT sözlüğünü ve bağlantı yapılandırmasını; `live_session.py` bağlantı/retry akışını, eşzamanlı gönderme-alma-izleme görevlerinin başlatılıp toplanmasını ve oturum sonu callback'ini taşır. `Live._config()`, `_stt_kwargs()`, `_converse()`, `_run_session()` ve `_session_end()` aynı imzalı delegeler olarak korunur. Durum alanları mevcut Live nesnesinde tutulur; ayrı kullanıcı veya istek kimliği üretilmez.

Ek kontrollü testler: yeni ses onayı yeni oturumda hazırlanır; 1011 sonrası sade modda ve bozuk resume olmadan retry; anahtar yokken/gizlilik engelinde bağlantı açmama; bir görev hata verdiğinde diğerlerini iptal edip toplama. Gerçek Gemini Live bağlantısı doğrulanmadı. `Live` hâlâ ortak durum, arayüz ve ses oturumu bileşenlerini bağlayan koordinatördür.

## Görev ve Ses Köprüleri

`web_tasks.py` 10 görev/not/takvim metodunu; `web_voice.py` 4 ses seçimi/hızı/mikrofon listeleme metodunu taşır. Bridge aynı API adlarını miras alır. Bağımlılıklar verilen `self._runtime` üzerinden okunur. Kullanıcı profili, ses önizlemesi ve motor olay kuyruğu mevcut bağlamda kalır. HTTP/SSE ve pencere yaşam döngüsü hâlâ web.py içinde bulunur.

Ek testler kullanıcı ayrımı, geçersiz etkinlikte kayıt yapmama, geçersiz ses tercihinde yan etki yapmama, hız sınırı ve mevcut Live oturumunda ses önizlemesidir. Gerçek takvim/ses servisi veya mikrofon aygıtı kullanılmamıştır.
