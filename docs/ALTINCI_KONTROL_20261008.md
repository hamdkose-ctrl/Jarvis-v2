# Altıncı Kontrol — 8 Ekim 2026

Önceki beş kontrolün düzeltmeleri dahildir. GitHub'a yükleme yapılmadı.

## Açılış Denetimi

Yeni sürümün açılışını denetleyen süreç kesildiğinde, aday uygulama normal kapatma isteğine cevap vermezse ikinci zaman aşımı oluşuyor ve uygulama açık kalabiliyordu. Normal açılış zaman aşımı yolu zorla kapatmayı içeriyordu; kesinti yolu içermiyordu.

İki yol aynı kapatma işlevini kullanır: önce normal kapatma, 10 saniyede kapanmazsa zorla sonlandırma ve sürecin kapanmasını bekleme. Kapatma sırasında zaten çıkmış sürecin yarış durumu da ele alınır. Kesintide bekleyen sürüm ve yedek kaydı korunur; sonraki açılış yeniden denetlenir. Başarısız açılışta mevcut geri alma davranışı sürer.

## Doğrulama

439 Python testi: 438 başarılı, Windows DPAPI gerektiren 1 test atlandı. JavaScript sözdizimi, 10 JavaScript davranış grubu ve 6 taklitli entegrasyon grubu başarılı.

Dört yeni regresyon testi kapanmayı reddeden çocuk sürecini, zaten çıkmış süreci, kapatma anında çıkış yarışını ve kesinti sırasında yedek kaydının korunmasını kapsar. Önceki gerçek alt süreç açılış/geri alma testleri de çalıştırıldı. Yeni zorla sonlandırma sınırları süreç taklitleriyle sınandı; gerçek Windows, mikrofon ve WhatsApp doğrulaması yapılmadı.
