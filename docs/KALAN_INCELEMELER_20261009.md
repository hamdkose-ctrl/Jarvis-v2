# Kalan Beş Alanın İncelemesi — 9 Ekim 2026

İnceleme çalışma/matematik, dosya/görsel, hafıza/görevler, geliştirme/güncelleme ve arayüz sırasıyla yapıldı. Bu paket önceki tüm yerel düzeltmeleri içerir. GitHub'a yükleme yapılmadı.

| Alan | İncelenen akışlar | Düzeltmeler |
| --- | --- | --- |
| Çalışma/matematik | Ek okuma, özgün PDF ve seçili alan, çöz/anlat hedefi, aritmetik kontrolü, kalıcı takip bağlamı; kaynak ekleme ve sınav girişleri | Yeni ek gönderildiğinde önceki sorunun metni model bağlamına taşınmaz. Ek olmadan takip sorusunda geçmiş korunur. |
| Dosya/görsel | İzinli dosya yolları, normal yükleme, fotoğraf saklama, not görselleri | Aynı saniyedeki fotoğraflar benzersiz ad alır. Aynı adlı eşzamanlı dosya yüklemeleri atomik ad rezervasyonuyla ayrı saklanır. |
| Hafıza/görevler | Profil kaydı, kayıt kimlikleri, onaylı bilgi adayları, görev ekleme/tamamlama/silme | Görev değişiklikleri ortak profil kilidiyle sıralanır; kimlik üretimi kilitlidir. Bulunmayan görev için hata döner. Bilgi adayı metni günlük dosyasına yazılmaz; yalnız aday sayısı kaydedilir. |
| Geliştirme/güncelleme | Aday kopya, bağımlılık ortamı, mevcut testlerin korunması, kaynak hash kontrolü, yayın günlüğü ve açılış geri alma | `./requirements.txt` ve Windows büyük/küçük harf farkı gibi yazımlar bağımlılık kontrolünü atlayamaz. Mevcut güvenli uygulama/geri alma testleri geçti. |
| Arayüz | Çalışma/matematik bekleme ve eski yanıt korumaları, dosya yükleme, sohbet ve mevcut sayfa davranış testleri | Telefona gönderilecek dosya yarıda yüklenmişse gönderim başlamaz, geçici dosya temizlenir ve API hatası döner. Matematik SVG çizimlerinin arka plan/metin renkleri açık arayüze uyarlandı. |

## Testler

7 yeni davranış testi: yeni matematik kaynağı ve takip bağlamı; aynı saniyede iki fotoğraf; aynı adlı 32 eşzamanlı dosya; 40 eşzamanlı görev ve geçersiz görev kimliği; bağımlılık yolu yazımları; yarım dosya yüklemesi; bilgi adayının günlükte gizli kalması.

513 Python testi çalıştı: 512 başarılı, Windows DPAPI testi ortam nedeniyle atlandı. JavaScript sözdizimi ve mevcut 10 davranış grubu ile 6 arayüz/motor entegrasyon grubu geçti. Güncel paketin test dökümü `MAIN_PAKET_TEST_SONUCU.txt` içindedir.

## Doğrulamanın sınırları

Bu, belirtilen veri ve hata akışlarının kod incelemesi ve regresyon kontrolüdür; bütün proje yollarının eksiksiz doğrulandığı iddiası değildir. Model açıklamasının öğretici kalitesi, görüntüdeki sembollerin doğru okunması ve desteklenmeyen ileri matematik otomatik garanti edilmez. Bağımsız matematik denetiminin kapsam dışı bulduğu adımlar doğrulanmış sayılmaz.

Gerçek Windows pencere yerleşimi ve ekran boyutları, mikrofon/ses donanımı, Android/Tailscale ve canlı model servisleri bu ortamda denenmedi. Arayüz kontrolleri kaynak, taklit DOM ve yerel HTTP testleriyle yapıldı. Görev kilitleri aynı süreçte ortak profil nesnesini korur; farklı süreçlerin aynı profil dosyasına eşzamanlı yazımı bu çalışmanın kapsamı dışındadır.

Jarvis'i kapatıp paketin `Jarvis` klasörünün tamamını kullanın. Kişisel profil ve API anahtarları pakete dahil değildir.
