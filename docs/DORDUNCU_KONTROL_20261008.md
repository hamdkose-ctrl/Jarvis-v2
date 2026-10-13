# Dördüncü Kontrol — 08.10.2026

Paket önceki tüm kontrol düzeltmelerini ve bu turdaki onay/geri alma düzeltmelerini içerir. GitHub’a yüklenmemiştir.

## Düzeltilenler
- Bilgisayar kapatma, klasör düzenleme ve WhatsApp onayında cümlenin herhangi bir yerinde `evet` veya `tamam` geçmesi yeterliydi. `evet ama gönderme` / `tamam kapatma` gibi olumsuz cümleler yanlış onaylanabiliyordu. Ortak `modules/confirmation.py` artık olumsuz ifadeleri önce değerlendirir; yalnız açık kısa olumlu cevapları kabul eder. `gönder` ve `düzenle` gibi işlem kelimeleri sadece ilgili onay bağlamında kabul edilir. Başka bir cümle eski onayı kaldırır; eski işlem bu cevapla yürütülmez.
- WhatsApp metni istenirken cümlenin içinde `iptal` kelimesi bulunması mesajı düşürüyordu. İptal komutu artık bu aşamada kısa açık komut olarak tanınır; `Toplantı iptal edildi` gibi gerçek mesaj metni korunur ve ayrıca gönderme onayı istenir.
- Yeni kurtarma kaydı olan geliştirmede elle geri alma önce dosyaları değiştirip sonra kurtarma kaydını işliyordu. İşlem ortasında kesilirse karma kaynaklar kalabiliyordu. Artık dosyalara yazmadan önce `rolling_back` durumu kaydedilir. Kurtarma tüm dosyaları doğrular, değişmiş dosyaları ezmez ve yarım geri almayı açılışta tamamlar.
- Geri alma kaydının kullanıcı sahibi kontrol edilir. Yedekten geri getirilen taslak durumu ezilmez; başarılı geri alma sonrasında taslak yeniden incelenebilir. Eski kurtarma kaydı olmayan, paket öncesi geliştirmeler için eski geri alma uyumluluğu korunur; yeni günlük koruması bu eski kayıtlara geriye dönük eklenmiş değildir.

## Doğrulama
425 Python testi: 424 başarılı; Windows DPAPI testi Linux ortamında atlandı. JavaScript sözdizimi, 10 davranış grubu ve 6 başsız bütünleşme grubu başarılı. Gerçek onay dallarında olumsuz/belirsiz cümlelerle PC kapatma/dosya hareketi/mesaj gönderme adaptörlerinin çağrılmadığı denetlendi. Açık mesaj onayı, iptal kelimesi içeren mesajın korunması ve sadece bağlama özgü olumlu kelimeler sınandı.

İki dosyalı gerçek geliştirme uygulandı; geri almada ikinci dosya yazımına hata enjekte edildi. İlk dosya yazılmadan önce kurtarma durumu kaydedildiği ve yarım kalan işlemin `recover` ile eski kaynak/taslak durumuna tamamlandığı doğrulandı. Başka kullanıcıya ait kurtarma kaydının kaynaklara dokunmadan reddedildiği sınandı. Ayrıntılı çıktı: `MAIN_PAKET_TEST_SONUCU.txt`.

Gerçek Windows, mikrofon, dosya taşıma ve WhatsApp otomasyonu burada çalıştırılmadı. Onay kontrollerinde bu dış adaptörler taklittir; dosyalı kurtarma testinde gerçek geçici dosyalar kullanılır. Önceki raporların test sayıları tarihseldir; bu ZIP’in güncel sonucu 425 testtir.
