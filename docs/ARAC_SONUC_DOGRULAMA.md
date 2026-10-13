# Araç sonuç doğrulama paketi

Bu paket önceki görev çekirdeği değişikliklerini içerir. Arayüz, Android ve ses davranışı değiştirilmez. Yeni runtime bağımlılığı yoktur.

## Tamamlanan
Araştırmada gerçek sayfa okuma uzunluğu ve kaynak URL; raporda boş olmayan dosya ve SHA-256; kodda mevcut taslağa ait başarılı test; tarayıcıda tüm adımların doğrulama kaydı, sayfa URL ve boş olmayan ekran dosyası aranır. Onay bekleyen veya kullanılamayan araç başarı sayılmaz.
Tarayıcı onay dönüşü de kontrol edilir. Devam ve bağımlı görevler sözleşmeli sonuçların dosya bütünlüğünü yeniden kontrol eder. Bozulmuş kanıt hafıza bağlamına alınmaz.

## Sınırlar
Yerel kanıt kontrolleri içerik doğruluğunu, görselin anlamını, gerçek hesapta yayını veya kodun bütün davranışlarını garanti etmez. Kod testi mevcut geliştirme modülünün taslak imzasına bağlı sonucudur; kaynağa uygulama değildir. Araştırma kaydı kaynak metninin uzunluğunu ve URL bilgisini saklar, tam sayfa arşivi değildir. Görev kayıtları kullanıcıya ait yerel veridir, kriptografik imzalı kanıt değildir. Eski kayıtlar korunur; doğrulama sözleşmesi olmayan çıktı yeni verify adımında başarı kanıtı sayılmaz.

## Doğrulama
52 odaklı görev/kurtarma/sonuç/ses köprüsü testi geçti. 20 Node grubu ve JavaScript sözdizimi kontrolleri geçti. Router smoke gerçek Bridge ve ana/ses yönlendirmesini model/OS taklitleriyle doğruladı. Tam Python çalıştırması 926 testte 8 Windows Ayarlar başarısızlığı ve 2 atlama ile bitti; bunlar önceki teslimde de bildirilen platform sorunlarıdır. Sonradan eklenen bir tamamlanmış tarayıcı kanıtı devam testi odaklı grupta ayrıca geçti. Canlı Windows, mikrofon, model ve hesap testleri yapılmadı.

## Kurulum
Jarvis kapalıyken mevcut klasörü yedekleyin. Paketteki klasörleri Jarvis ana klasörüne birleştirip aynı dosyaları değiştirin. Önceki çekirdek paketini ayrıca kurmak gerekmez. Windows üzerinde run_tests.bat çalıştırın. Yerel değişiklikler otomatik güncellemeyle değiştirilebilir; bu paket GitHub’a gönderilmedi.
