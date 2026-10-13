# Sohbet, Ses ve İstek Güvenliği — 9 Ekim 2026

Başlangıç: `e18e8de8a74928c1e00470918a7af3d874fba50c`.
Bu sürümde dört bulgu da kaynak incelemesiyle doğrulandı. Düzeltme öncesinde
eklenen ilk dokuz regresyon testi başarısız oldu (5 başarısızlık, 4 hata).

## Değişiklikler

- Yeni sohbet yalnız seçilen kullanıcının devam eden/kuyruktaki isteklerini iptal eder,
  kısa konuşma durumunu yeniler ve bekleyen fotoğrafı temizler. İşlem onayı, eksik bilgi
  soruları, eski doküman ve kısa sesli cevap taşınmaz. Kalıcı profil ayarları ve geçmiş
  silinmez; başka kullanıcının bekleyen işlemleri etkilenmez.
- Çevrimiçi `voice.speak()` her parçada yalnız seçilen sesi iki kez dener. Başarısız
  olursa kalan okumayı durdurur; varsayılan Ahmet veya yerel sese geçmez. Hata ekranın
  sistem bildirimi olarak gösterilir. Sonraki cevap yine seçilen sesi kullanır.
  Kullanıcının açıkça seçtiği yerel gizlilik modunun yerel TTS davranışı korunur.
- Canlı modelin komut aracı normal istek günlüğüne kullanıcıya bağlı kimlikle
  kaydolur; 90 saniyelik varsayılan süre ve kooperatif iptal bağlamında çalışır.
  İptal normal bir komut hatası gibi açıklama modeline gönderilmez.
- Telefon kaydı kabul edilirken kimlik oluşturulur. Çeviri ve komut aynı kimliği
  taşır. Çeviri sonrası yeni `submit()` çağrısıyla yeni kimlik üretilmez. İptal veya
  süre dolması çeviri öncesinde ve sonrasında kontrol edilir. Çeviri tamamlanınca
  `activate(..., complete=False)` aynı kaydı tekrar kuyruk durumuna bırakır;
  komut yürütülünce normal tamamlanma kaydı yazılır. İptal durumları diriltilmez.
- Telefon API'si kayıt kabul edilmezse başarı bildirmez; kabulden önceki disk
  hatasında veya reddetmede geçici ses dosyasını temizler.

## Kontroller

`tests/test_conversation_request_safety.py`: yeni sohbetten sonra eski onayın
`confirmed=True` ile çalışmaması, tüm bekleyen alanların sıfırlanması, profil ve
diğer kullanıcı korunması; canlı komutun kendi kimliği, süre dolması, aynı ve ayrı
iş parçacığından iptal; telefon kaydının çeviri sırasında/öncesinde iptali,
çeviri sonrası süre dolması, tek kimlikle komuta geçişi; kayıt girişinde disk
hatasından sonra aynı kimlikle yeniden gönderme; seçilen ses başarısızken ses
değişmemesi, sonraki cevapta aynı sesi yeniden deneme, ekranda hata; telefon
API'sinin disk hatası/reddetme sonucunu ve geçici dosya temizliğini kapsar.

Önceki `tests/test_request_journal_failures.py` disk hatası regresyonları korunur.
Yeni istek kimlikleri ve görünür hata bildirimi için eski bağlantı testlerinin
beklentileri güncellendi; kullanıcı sahipliği, bağlam temizliği, durdurma süresi
ve silinmiş kullanıcı kontrolleri korunur.

## Doğrulama sınırları

Tam doğrulama: 555 Python testi (554 başarılı, 1 atlanan), JavaScript sözdizimi,
10 JavaScript davranış grubu ve 6 smoke grubu başarılı. Bu sayılar Linux test
ortamına aittir; kullanıcının Windows testi olarak değerlendirilmemelidir.

Denemeler gerçek orkestrasyon ve istek günlüğüyle, taklit ses/model/donanım
bağımlılıklarıyla yapıldı. Gerçek mikrofon, hoparlör, çevrimiçi TTS, telefon ve
Windows işlemleri bu denemelerde kullanılmadı. Bu düzeltmeler gerçek cihazdaki
önceki ses sorununun kesin nedenini kanıtlamaz.

İptal kooperatiftir: iptal kontrol noktasından sonraki iş engellenir. Başlamış
harici servis çağrısı zorla kesilmez; bitince sonucu iptal kontrolünden geçer.
Daha önce gerçekleşmiş bilgisayar işlemi bu mekanizmayla geri alınmaz.
