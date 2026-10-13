# Modüller Arası Bağlantı Kontrolü — 9 Ekim 2026

Güncel paket önceki main ayrıştırması, modül içi ve dış bağlantı düzeltmelerini içerir. GitHub'a yükleme yapılmadı.

## İncelenen bağlantılar

| Bağlantı | Doğrulama |
| --- | --- |
| `engine_runtime` → bütün kayıtlı işleyiciler | Her işleyicinin doğru modülden geldiği ve aynı `EngineContext` örneğine bağlandığı test edilir. Canlı sesin kullanıcı bağlamı sarmalayıcıları da kontrol edilir. |
| Bütün `engine_*` modülleri → çalışma bağımlılıkları | Doğrudan `runtime` alanlarına yapılan başvuruların başlangıç durumunda veya dışa açılan alanlarda tanımlı olduğu kontrol edilir. Bu statik kontrol, bütün çalışma yollarını tek başına doğrulamaz. |
| Komut/kuyruk/canlı ses → çıktı | Eşzamanlı işlerde kaynak, istek kimliği ve yazım düzeltme durumu birbirine taşınmaz. Çıktı günlüğünün iki farklı işin istek kimliklerini koruduğu gerçek bağlamla test edilir. |
| Çok adımlı komut/makro → oturum → seslendirme | Bir adımın kısa sesli yanıtı toplu sonuç yerine yeniden kullanılmaz. Kapanış başlamışsa çok adımlı komut ilk adımı bile çalıştırmaz. |
| `main` uyumluluk katmanı → çalışma durumu | Yeni bağlam alanlarının geçici değiştirilmesi ve geri yüklenmesi aynı motor üzerinden çalışır; modülde ayrı gölge değer oluşmaz. |

## Düzeltilen durum aktarımı

Komut kaynağı, istek kimliği ve yazım düzeltme bilgileri daha önce motorun ortak alanlarıydı. Canlı ses ve olay döngüsü farklı iş parçacıklarından eriştiğinde bu bilgiler birbirine karışabiliyordu. Bu dört alan artık `ContextVar` ile çalışma bağlamına aittir. Profil, kuyruk, kilitler ve cihaz bayrakları mevcut motor durumunda kalır; kullanıcı işlemleri mevcut yürütme kilidiyle sıralanır.

Canlı ses komutu kendi kaynak/istek bilgilerini kurar; eski istek kimliğini ve eski yazım düzeltme metnini kullanmaz. Başlangıç veya çıktı hatasında da önceki bağlam geri yüklenir. Olay döngüsü tamamlanan veya iptal edilen işin kimliğini temizler.

Çok adımlı işlem ve makro bittiğinde tek bir adımın `speech_override` değeri temizlenir. Böylece dönen toplu yanıt yerine yalnız bir adımın kısa cevabı okunmaz.

## Test sonucu ve sınırlar

10 yeni bağlantı/durum aktarımı testi eklendi. 506 Python testi çalıştı: 505 başarılı; Windows DPAPI testi ortam nedeniyle atlandı. JavaScript ve mevcut entegrasyon grupları başarılı. Tam kayıt `MAIN_PAKET_TEST_SONUCU.txt` içindedir.

Testler gerçek modül bağlama, iş parçacığı ve çıktı/oturum nesnelerini kullanır; dış model, donanım ve bazı kullanıcı kayıtları test bağımlılıklarıyla değiştirilir. Gerçek mikrofon, Windows ses çıkışı, Android/Tailscale ve canlı model servisleri bu ortamda doğrulanmadı.

Kurulumda Jarvis'i kapatıp paketin `Jarvis` klasörünün tamamını kullanın.
