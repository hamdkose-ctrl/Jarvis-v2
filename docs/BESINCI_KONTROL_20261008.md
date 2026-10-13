# Beşinci Kontrol — 8 Ekim 2026

Bu paket önceki dört kontrolün düzeltmelerini de içerir. GitHub'a yükleme yapılmadı.

## Düzeltilen Sorunlar

- WhatsApp gönderimi ana komut tamamlandıktan sonra arka planda devam ediyordu. Ayrı kullanıcıya bağlı işlem kaydı eklendi; ana komut bitse de gönderim iptal edilebilir. İptal edilmiş ana komut yeni arka plan görevi başlatamaz.
- Arka plan gönderimindeki hata ve iptal sonuçları, işlemi başlatan kullanıcının sohbetine bildirilir.
- Aynı anda iki WhatsApp gönderimi klavyeyi kullanamaz. Kilitte bekleyen işlem de iptal edilebilir.
- Pencere beklemeleri ve gönderme tuşundan önce iptal kontrolü yapılır. WhatsApp penceresi bulunamazsa yazma ve Enter adımları uygulanmaz.
- Sonuç metni teslim edildiğini iddia etmez; yalnızca gönderme komutunun uygulandığını belirtir.

## Doğrulama ve Sınırlar

435 Python testi: 434 başarılı, Windows DPAPI gerektiren 1 test atlandı. JavaScript sözdizimi, 10 JavaScript davranış grubu ve 6 donanım/model taklitli entegrasyon grubu başarılı.

Yeni 10 test; ana komut sonrası iptal, kullanıcı ayrımı, hatanın bildirilmesi, kilit sırasında iptal, eşzamanlı gönderim, pencere bulunamaması ve bekleme iptalini kapsar. Testler gerçek mesaj göndermez.

Gerçek Windows/WhatsApp, mikrofon ve görsel arayüz denemesi bu ortamda yapılmadı. Klavye otomasyonu WhatsApp sürümü ve pencere odağına bağlıdır. Son Enter uygulanmışsa iptal mesajı geri çekemez; iptal kontrolleri yapılmış gönderimi geri alma garantisi değildir.
