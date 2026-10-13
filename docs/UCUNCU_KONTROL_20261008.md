# Üçüncü Kontrol — 08.10.2026

Bu paket önceki iki kontrolün tüm kaynaklarını ve bu turdaki makro/yeniden başlatma düzeltmelerini içerir. GitHub’a yüklenmemiştir.

## Düzeltilenler
- Makro yürütücüsü yeni uygulama onayı ve diğer eksik bilgi sorularında durmuyordu; tüm adımlar tamamlanmış gibi yanıt veriyordu. Artık bütün bekleme alanları denetlenir. Kullanıcının cevaplaması gereken soru ekrana gelir ve kalan adımlar çalışmaz.
- Makroda kullanıcı değişimi, iptal ve kapanış kontrol edilir. Kullanıcı değişince kalan işlemler yeni kullanıcıya taşınmaz. Başta yakalanan oturumun `_in_macro` işareti hata/iptal/kullanıcı değişiminde temizlenir.
- Gecikmeli Jarvis kapatma niyeti hemen `closing` işaretiyle kaydedilir. Hem makro hem çok adımlı komut, 1,8 saniyelik kapanış zamanlayıcısını beklemeden zinciri durdurur.
- Makro adımları arasındaki kısa bekleme korunur; son adımdan sonra gereksiz bekleme kaldırıldı. Tamamlanma yanıtı gerçekten çağrılan adımlar üzerinden oluşturulur. Bu, dış uygulamaların gerçek başarı durumunun tümünü doğruladığı anlamına gelmez.
- Yeniden başlatmada eski pencere/bağlantı yeni süreç oluşturulmadan kapatılıyordu. Süreç oluşturma başarısızsa mevcut pencere, motor ve bağlantı korunur; kapatma zamanlayıcısı başlatılmaz. Başarılı süreç oluşturulduktan sonra eski süreç kapanmaya hazırlanır. Eski tarayıcı pencerelerini yeni GUI kendi açılışında kapatır.

- Makro adı tam eşleşiyorsa ek atılmış alternatif addan önce seçilir. Alternatif eşleşmelerin sırası da sabittir; örneğin kayıtlı `notu` ve `not` arasında `notu` isteği yanlış makroya gitmez.

## Doğrulama
415 Python testi: 414 başarılı, Windows DPAPI testi Linux ortamında atlandı. JavaScript sözdizimi, 10 davranış grubu ve 6 başsız bütünleşme grubu başarılı. Makrolarda her bekleme türü, iptal, kullanıcı değişimi ve kapanış; gerçek kapatma niyeti işareti; süreç oluşturma hatasında pencerenin korunması; yeniden başlatmada eski açılış işaretlerinin aktarılmaması sınandı. Ayrıntılı çıktı: `MAIN_PAKET_TEST_SONUCU.txt`.

Gerçek Windows yeniden başlatma, mikrofon, ses donanımı ve tarayıcı görünümü bu ortamda doğrulanmadı. Bu turdaki süreç oluşturma hatası/yeni başlatma çağrısı testleri süreç adaptörünün taklidiyle çalışır; önceki gerçek alt süreç açılış kurtarma testleri de genel koşuda yeniden geçti. Eski raporlardaki test sayıları tarihseldir; bu ZIP’in güncel sayısı 415’tir.
