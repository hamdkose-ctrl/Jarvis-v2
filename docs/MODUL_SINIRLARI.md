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
| `modules/stt_fixes.py` | Yaşayan STT düzeltme sözleşmesi: `DEFAULT_FIXES`, `parse_fixes`, `format_fixes` | Ses veya tanım motoru çağırmaz; okuyucuları `learning.py` ve arayüz ayarları. |
| `modules/live.py` ve `live_*` yığını | **11 Kasım 2026'da emekli edildi** | Aşağıdaki "Canlı …" bölümleri geçmiş taşımayı anlatır; dosyalar artık yoktur. Kanıt: `tests/test_live_retirement.py`. |

## Canlı Araç ve Transkript Bileşenleri

> **Geçmiş bölüm (11 Kasım 2026):** aşağıda adları geçen `live_tool_runner.py`, `live_transcripts.py`,
> `live_tools.py` ve `Live` nesnesi emekli edildi; mikrofon ve oturum yaşam döngüsü artık bu
> sınıfta değil, tek ses sahibi (`voice_core`/`voice_runtime`) ile yaşayan STT yollarındadır
> (`wakeword`, `voice.listen`, `local_stt`, `stt_guard`). Kanıt ve gerekçe:
> `tests/test_live_retirement.py`, `docs/agents/ses-video.md`.

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

`Bridge` hâlâ HTTP/durum/pencere bileşimini taşır. `Live` koordinatörü ve oturum/ses yaşam döngüsünü tek nesnede toplayan yapı 11 Kasım 2026'da emekli edildi; asistan konuşmasının tek sahibi `modules/voice_core.py` + `modules/voice_runtime.py`, mikrofon/STT sahipleri `wakeword.py`/`voice.py`/`local_stt.py`/`stt_guard.py`'dir. Bu ayrım bütün büyük sınıfların bitirildiği anlamına gelmez. Android v1 kurulum QR'ında ham anahtar aktarımı sürer; güncel Android istemcisi ve APK ile birlikte protokol değişikliği gerekir.

## Mikrofon Bileşeni

> **Geçmiş bölüm:** `live_microphone.py` emekli edildi. Yaşayan tek sürekli mikrofon okuyucusu
> `modules/wakeword.py` ( fiziksel `sd.InputStream` açar/bırakır) ve tek seferlik
> `voice.listen`/`local_stt` yollarıdır; mikrofon anahtarı kapanınca akışın gerçekten bırakılması
> `tests/test_mic_hard_off.py` ile bağlanır. Hoparlör yankısı süzgesi `stt_guard` + tek sahibin
> `playback_started` sınırıdır; 1,2 sn bekleme ve metin yankı filtresi AEC değildir.

`modules/live_microphone.py` mikrofon stream okumasını, kare biriktirmeyi, kazanç hesabını, uyanmayı ve yankı korumasını taşır. Eski `Live._mic_loop()`, `_agc()` ve `_on_frame()` metotları aynı nesneye delege eder. Mikrofon kapanınca stream bırakma, kazanç tavanı, iki güçlü uyanma karesi ve hoparlör sonrası yankı aralığı korunur. Bu taşıma yeni STT modeli veya ses tanıma ayarı eklemez.

Bu aşamada 6 yapay ses/cihaz testi eklenmiştir; gerçek Windows mikrofon gecikmesi, algılama doğruluğu ve ses aygıtı yaşam döngüsü cihazda doğrulanmamıştır. Oturum yönetimi ve durum alanları hâlâ Live içinde bulunur.

## Oturum Bileşenleri

> **Geçmiş bölüm:** `live_session.py` ve `live_session_config.py` emekli edildi. Türkçe dil kodu ve
> özel sözlük artık bir bağlantı yapılandırması değil; yaşayan STT yollarının (`voice.recognize`,
> `local_stt.hint_prompt` + `stt_words`) kendi ayarıdır ve hiçbir hata kullanıcı ayarına kalıcı
> yazılmaz.

`live_session_config.py` STT sözlüğünü ve bağlantı yapılandırmasını; `live_session.py` bağlantı/retry akışını, eşzamanlı gönderme-alma-izleme görevlerinin başlatılıp toplanmasını ve oturum sonu callback'ini taşır. `Live._config()`, `_stt_kwargs()`, `_converse()`, `_run_session()` ve `_session_end()` aynı imzalı delegeler olarak korunur. Durum alanları mevcut Live nesnesinde tutulur; ayrı kullanıcı veya istek kimliği üretilmez.

Ek kontrollü testler: yeni ses onayı yeni oturumda hazırlanır; 1011 sonrası sade modda ve bozuk resume olmadan retry; anahtar yokken/gizlilik engelinde bağlantı açmama; bir görev hata verdiğinde diğerlerini iptal edip toplama. Gerçek Gemini Live bağlantısı doğrulanmadı. `Live` hâlâ ortak durum, arayüz ve ses oturumu bileşenlerini bağlayan koordinatördür.

## Görev ve Ses Köprüleri

`web_tasks.py` 10 görev/not/takvim metodunu; `web_voice.py` 4 ses seçimi/hızı/mikrofon listeleme metodunu taşır. Bridge aynı API adlarını miras alır. Bağımlılıklar verilen `self._runtime` üzerinden okunur. Kullanıcı profili, ses önizlemesi ve motor olay kuyruğu mevcut bağlamda kalır. HTTP/SSE ve pencere yaşam döngüsü hâlâ web.py içinde bulunur.

Ek testler kullanıcı ayrımı, geçersiz etkinlikte kayıt yapmama, geçersiz ses tercihinde yan etki yapmama, hız sınırı ve tek ses sahibinin katalogundan önizlemedir (`tests/test_local_stt.py`, `tests/test_voice_runtime_bridge.py`). Gerçek takvim/ses servisi veya mikrofon aygıtı kullanılmamıştır.
