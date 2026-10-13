# Ana Ekrana Eklerken Bağlantı

Bağlantı anahtarı yalnız localStorage içinde tutuluyordu. Ayrı depolama kullanan kurulu web uygulaması açıldığında bu anahtar yoktu. Özellikle iOS'ta tarayıcı localStorage verisi kurulum sırasında taşınmaz; çerezler taşınabilir. Kaynak: https://webkit.org/blog/14787/webkit-features-in-safari-17-2/

HTTPS bağlantısında kullanıcı anahtarıyla doğrulanan, Secure / HttpOnly / SameSite=Strict ve yalnız /api/web-session yoluna ait oturum çerezi eklenir. Ana ekrandan açılışta yerel anahtar yoksa bu oturumdan geri yüklenir. Ana Ekrana Ekle işlemi öncesinde oturumun saklanabildiği kontrol edilir; başarısızsa kullanıcıya bildirilir. Anahtar URL veya manifest içine yazılmaz. Normal API'ler çerezle yetkilendirilmez; X-Token şartı korunur. Silinmiş kullanıcı ve yenilenmiş anahtar reddedilir. Çerezin ömrü bir yıldır; PC'de anahtar yenileme daha erken iptal eder.

## Kullanım

1. PC'de bu paketi kullanıp Jarvis'i yeniden başlatın.
2. Telefon tarayıcısında PC'nin Telefon sayfasındaki güncel HTTPS QR bağlantısını açın ve bağlantıyı bekleyin.
3. Eski ana ekran kısayolu varsa yeni kurulumdan önce kaldırıp bu sayfadan Ana Ekrana Ekle işlemini tekrar yapın. Eski kurulumun yerel notları varsa önce metinlerini alın veya PC'ye eşitleyin; kurulum kaldırılması yerel veriyi silebilir.
4. Yeni simgeden açıp mesaj gönderin. Aynı HTTPS adresini kullanın; HTTP/HTTPS, port veya adres değişikliği ayrı bağlantıdır.

## Doğrulama

Gerçek yerel HTTP sunucusunda oturum kaydetme/geri yükleme, kullanıcı ayrımı, iptal edilmiş anahtar, eksik başlık ve normal API'lerde çerez reddi test edildi. JavaScript davranış testinde boş uygulama hafızasından oturum geri yüklendi. Bu testler fiziksel telefon kurulum testi değildir. Eski iOS sürümleri veya çerez taşımayan tarayıcılar için otomatik aktarım doğrulanmış değildir.

Bu paket önceki kompakt sohbet ve mobil arayüz değişikliklerini içerir. Android APK içermez.
