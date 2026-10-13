# Çalışma bölümü incelemesi · 7 Ekim 2026

Çalışma kaynakları, konu anlatımı, soru havuzu, cevap değerlendirme, yanlış defteri, deneme, son üç yıl analizi, çalışma programı ve arayüzün kullanıcı/konu sürekliliği incelendi.

## Düzeltilen davranışlar

- Küçük soru havuzunda bütün sorular son sorular listesine girince alıştırma duruyordu. Yeni sorular öncelikli; havuz tükenince kontrollü tekrar yapılır ve mümkünse en son soru hemen tekrar edilmez. Konu filtresi korunur.
- Hızlı çift cevap öğrenme istatistiğini iki kez artırabiliyordu. Alıştırmaya deneme kimliği eklendi; aynı deneme ikinci kez kayıt üretmez, eski denemenin cevabı yeni denemeye uygulanmaz. Arayüz de devam eden cevap isteği sırasında ikinci gönderimi önler.
- Soruda bulunmayan şık yanlış cevap sayılıyordu. Artık geçersiz seçim istatistiğe eklenmeden reddedilir. Değerlendirme, kaynakta bulunan cevap anahtarına dayanır; model doğru şık uydurmaz.
- Yeni sınav yılı eklenince son üç yıl havuzundan düşen aktif deneme soruları kaybolabiliyordu. Deneme, başlangıçtaki soru/şık/cevap anahtarını saklar; resmi anahtar arayüze cevap verilmeden gönderilmez. Eski deneme kimliğiyle yeni deneme cevaplanamaz.
- Aynı adlı iki dosya, farklı oturumlar veya değişmiş içerik tek yükleme gibi algılanabiliyordu. İçerik özeti, tür, yıl, dönem ve oturum birlikte karşılaştırılır. Arka plan okuyucusu dosyanın sabit kopyasını kullanır; özgün dosyanın sonradan değiştirilmesi yüklenen kaynağı değiştirmez. Eski kaynaklar içerik özeti taşımadığından ilk yeniden yüklemede yeni kayıt oluşabilir.
- Yükleme sürerken kaynaklar temizlenirse eski yükleme kaynakları geri getirebiliyordu. Temizleme kaynak sürümünü değiştirir; eski okuyucu sonuçlarını sonradan kaydetmez. Temizleme aktif kaynak/konu/denemeyi de sıfırlar.
- Son anlatılan konu yalnız bellekteydi. Konu ve ders bağlamı profil içinde saklanır; takip açıklamalarında aktif konu korunur. Seçili kaynağa geçmek önceki konu kilidini kaldırır. Kaynaktan Çalış modunda aktif kaynak takip sorularında kullanılır.
- Boş model yanıtı ilerleme kaydı oluşturabiliyordu. Boş yanıt başarı olarak kaydedilmez.
- Kısmen etiketlenmiş soru analizi yüksek güven gösterebiliyordu. Güven, toplam/etiketli/anahtarlı soru kapsamına göre hesaplanır; bu sayılar arayüzde görünür.
- Bozuk veya boş çalışma günü ayarı program döngüsünü kilitleyebiliyordu. Kayıtlı gün/saat/süre güvenli varsayılanlarla normalize edilir.
- Geç gelen ders, sade anlatım, medya ve genel durum yanıtları yeni kullanıcı/konuyu değiştirebiliyordu. İstek sahibi ve güncel istek kontrol edilir. Kullanıcı değişiminde eski alıştırma, medya ve bekleme durumları temizlenir.

## Doğrulama

14 yeni Python çalışma senaryosu gerçek yerel dosya/soru/profil verisiyle kontrol edildi. Yeni JavaScript davranış grubu geç yanıtların kullanıcı/konu ayrımını, çift gönderimi, soru kimliğini, konu filtresini ve medya/durum ayrımını test eder. Modeller ve arayüz DOM adaptörleri taklit edilir.

Gerçek kullanıcı kitaplarıyla PDF çıkarım kalitesi, taranmış PDF için OCR, canlı modelin konu anlatım kalitesi, YouTube/Wikipedia bağlantısı ve Windows sesli anlatımı bu ortamda doğrulanmadı. Metinsiz tarama hâlâ okunabilir metin bulunamadı hatası verebilir; otomatik OCR eklendiği iddia edilmez. Bu kontroller kullanıcının gerçek cihaz/kaynaklarıyla yapılmalıdır.

Son tam paket doğrulaması: 276 Python testi (275 başarılı, 1 Windows DPAPI testi Linux üzerinde atlandı), 9 JavaScript davranış grubu ve 6 Python entegrasyon smoke akışı başarılı. ZIP dosya bütünlüğü ve kaynak byte eşleşmesi kontrol edildi.
