# Main Modüler Ayrıştırma — 9 Ekim 2026

`main.py` 42 satırlık başlatma ve uyumluluk katmanına indirildi. Komut satırı ile web/araç içe aktarmaları aynı motora bağlanır. Eski dosyanın kopyası üretim kodunda tutulmuyor. İş mantığı 9 modüle, bağımlılıkları birleştirme ve ortak durum ise ayrıca bir çalışma zamanı modülüne taşındı.

| Dosya | Sorumluluk |
| --- | --- |
| `main.py` | Başlatma; mevcut web/telefon çağrılarının aynı çalışma durumuna erişimi |
| `modules/engine_runtime.py` | `EngineContext`, bağımlılıkların bağlanması, başlangıç durumu |
| `modules/engine_loop.py` | Olay döngüsü, başlatma ve kapatma koordinasyonu |
| `modules/engine_commands.py` | Komut işleme; mevcut `command_manager` yönlendirmesi ve devam eden komut dalları |
| `modules/engine_context.py` | Kullanıcı/profil/oturum bağlamı, kullanıcı değiştirme, ses tercihleri |
| `modules/engine_voice.py` | `VoiceSession`, mikrofon dinleme, uyandırma, seslendirme ve canlı konuşma bağlamı |
| `modules/engine_queue.py` | Metin/ses/görsel olaylarının kuyruğa alınması |
| `modules/engine_output.py` | Arayüz çıktısı, cevap düzenleme, belge ve pano çıktıları |
| `modules/engine_background.py` | Hatırlatmalar, arka plan bildirimleri ve takılma izleme |
| `modules/engine_sequence.py` | Çok adımlı komutlar ve kapatma |
| `modules/engine_tools.py` | Belge/çalışma/mesaj ve diğer araçların komut bağlantıları |

## Durum ve uyumluluk

Fonksiyonlar ihtiyaç duydukları çalışma bağlamını açık `runtime` parametresiyle alır. Kuyruk, kilitler, durdurma sinyalleri, kullanıcı oturumları ve profil önbelleği `EngineContext` içinde tutulur. Ayrı bağlamlar bu değişkenleri paylaşmaz. Alt sağlayıcıların mevcut modül düzeyindeki durumları bu çalışmayla bütünüyle bağımsızlaştırılmış değildir.

`main` üzerinden erişen mevcut web/telefon kodu aynı bağlama yönlendirilir; durumun ikinci kopyası oluşturulmaz. Dinleme ve seslendirme, ana döngünün içindeki gizli fonksiyonlar yerine `VoiceSession` metotlarıdır. Mevcut `main_documents`, `main_planner`, komut yöneticisi ve sağlayıcılar korunmuştur. Dinamik kod yürütme veya eski monolitik dosyayı arka planda çalıştırma kullanılmaz.

Mevcut güvenli geliştirme, test/geri alma, güncelleme kurtarma, matematik doğrulama ve arayüz düzeltmeleri bu pakette korunur. GitHub'a gönderme veya uzak `main` birleştirmesi yapılmamıştır.

## Doğrulama ve sınırlar

Yeni testler gerçek çalışma bağlamlarını, web uyumluluk katmanını, bağlama bağlı komut/kuyruk işleyicilerini, olay döngüsünün kapanmasını, ses tercihlerinin aktarılmasını ve gereksiz günlük dosyası açılmamasını doğrular. Donanım ve dış servis çağrıları bu testlerde taklit edilir. Mevcut regresyon, JavaScript ve arayüz entegrasyon grupları da çalıştırılır. Paketin kesin test dökümü `MAIN_PAKET_TEST_SONUCU.txt` içindedir.

Gerçek Windows mikrofonu, ilk açılıştaki gecikme, konuşma algılama başarısı ve fiziksel ses çıkışı bu ortamda doğrulanmadı. Main ayrıştırmasının tamamlanması bu sorunların kendiliğinden çözüldüğü anlamına gelmez.

Bu çalışma main dosyasını ayırmayı tamamlar. Bütün JARVIS mimarisinin tamamlandığı iddiası değildir: komut dallarının tamamen ayrı alan işleyicilerine ayrılması ve sağlayıcıların bağımsız yaşam döngülerine kavuşması daha geniş mimari çalışmalardır.
