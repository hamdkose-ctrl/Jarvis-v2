# Modüllerin Dış Bağlantıları — 9 Ekim 2026

Bu paket main ayrıştırmasını, modül içi kontrolü ve önceki düzeltmeleri içerir. GitHub'a yükleme yapılmadı.

## Bağlantı incelemesi

| Bağlantı | Kontrol ve sonuç |
| --- | --- |
| Web HTTP → Bridge → motor kuyruğu | Gerçek yerel HTTP sunucusuna gönderilen metin, doğru kullanıcı ve istek kimliğiyle gerçek motor kuyruğuna ulaştı. Kuyruk reddi API hatası olarak döner. |
| Web sohbet → doğrudan durdurma | `dur` kuyruğa alınmadan işlenir; arayüz, gelmeyecek bir asistan yanıtını beklemeyi bırakır. Normal komutta bekleme sürer; API hatasında temizlenir. |
| Telefon → motor → yanıt günlüğü | Kullanıcı ve istek kimliği birlikte eşleştirilir. Silinen/bilinmeyen kullanıcı bilgisayar kullanıcısına düşmez. İptal, kapanış veya kuyruk reddinde gereksiz bekleme yapılmaz. |
| Telefon → durdurma | Telefonun `dur` isteği artık motorun ilgili kullanıcının işlemlerini iptal eden yoluna ulaşır; yalnızca `Tamam` demekle kalmaz. |
| Komut satırı → `main` kullanan web/araçlar | `python main.py` ile oluşan modül `main` adıyla da kaydedilir. Web/araç içe aktarmaları ikinci motor oluşturmaz. Giriş dosyası bu bağlantı düzeltmesiyle 42 satırdır. |
| Ses/görsel kuyruğu → kullanıcı bağlamı | Kullanıcı gönderim anında sabitlenir; daha sonra PC kullanıcısı değişirse eski dosya yeni kullanıcı adına işlenmez. |
| Canlı ses, araçlar, kullanıcı anahtarları, geliştirme ve güncelleme | Mevcut bağlam/Bridge ve regresyon kontrolleri geçti. Donanım ve model/işletim sistemi çağrıları testlerde taklit edildi. |

## Düzeltilen diğer bağlantı riski

Telefon soru gönderiminde `TypeError` yakalandığında komut eski imzayla yeniden gönderiliyordu. Hata motorun içinde oluşmuşsa bu ikinci gönderim işlemi yineleyebilirdi. Yeni paket aynı dağıtımdaki istek kimlikli motor sözleşmesini kullanır; böyle bir hatada komutu tekrar göndermez. Eski, istek kimliği desteklemeyen motorla dosyaları karıştırmak desteklenmez.

## Doğrulama ve sınırlar

11 yeni Python bağlantı testi ve sohbetin doğrudan durdurma/kuyruk hatası için JavaScript davranış kontrolleri eklendi. 496 Python testi çalıştı: 495 başarılı, Windows DPAPI testi ortam nedeniyle atlandı. JavaScript ve mevcut arayüz entegrasyon grupları başarılı. Tam kayıt `MAIN_PAKET_TEST_SONUCU.txt` içindedir.

Yerel HTTP ve modüller arası çağrılar doğrulandı. Gemini/Groq/Ollama sunucularına canlı bağlantı, kota ve kullanıcının anahtarlarının geçerliliği bu kontrolde denenmedi. Gerçek Android/Tailscale bağlantısı, Windows mikrofonu ve ses çıkışı da fiziksel cihazda doğrulanmalıdır. Bu sonuçlar servislerin her an erişilebilir olduğunu garanti etmez.

Kurarken Jarvis'i kapatıp `Jarvis` klasörünün tamamını kullanın; yalnız `main.py` dosyasını değiştirmeyin.
