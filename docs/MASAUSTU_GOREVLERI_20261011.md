# Masaüstünde işlem yapan görev akışı — 11 Ekim 2026

## Kurulum

Bu güncelleme önceki komut yürütme düzeltmelerini de içerir ve güncel GitHub `main` koduyla birleştirilmiştir. PR birleştirildikten sonra Jarvis'in mevcut GitHub güncelleme akışını kullan. Yerelde farklı kaynaklar varsa önce yedekle; aday testleri tamamlanmadan kurulum yapma. Ardından `run_tests.bat` ve `baslat.bat` çalıştır.

Kullanıcı ayarı, API anahtarı veya geliştirme şifresi depoya eklenmez. Yeni Python paketi/ücretli servis eklenmedi. Windows'un yerleşik UI Automation altyapısı, PowerShell ve mevcut model bağlantısı kullanılır. Android bu değişiklikte düzenlenmedi.

## Kullanım

Örnek: `PC görevi: Hesap Makinesi | 12 ile 7 topla`

Sesli örnek: `PC görevi hesap makinesi 12 ile 7'yi topla`. Hesap Makinesi/Not Defteri için noktalama işareti gerekmez. Aynı adlı iki gerçek pencere varsa kullanmak istediğini öne getirip `PC görevi devam` de. Windows'un DWM ile gizlediği UWP pencereleri aday listesine alınmaz; seçilen pencerenin tutamacı işlem boyunca korunur.

Hedef açık değilse mevcut uygulama açma altyapısıyla açılmaya çalışılır. Birden fazla pencere varsa tam başlığı belirt. Uygulama içinde iş yapma isteği açık bir hedefle normal cümle olarak da söylenebilir; model bunu `desktop_task` olarak yönlendirebilir. Doğrudan biçim yönlendirme belirsizliğini azaltır.

- `PC görevi durumu`: kayıtlı hedef, durum ve doğrulanan adım sayısı.
- `PC görevi devam`: son durum yeniden okunarak sürdürme. Bekleyen masaüstü işi varken normal `devam et` de bu yola gider; şifreli geliştirme bağlamı önceliğini korur.
- `PC görevi cevap: ...`: görev bir soru sormuşsa cevabı iletme.
- `PC görevi iptal`: bekleyen görevi/onayı kapatma.
- `Dur`: çalışan isteği mevcut istek iptal mekanizmasıyla durdurma. Windows kontrol işçisi de iptal kontrolünde sonlandırılır.
- `PC onayla <kimlik>`: ekrandaki belirli işlem önizlemesini uygulama. Onay 120 saniyede veya ekran değiştiğinde geçersiz olur.

## Gerçekten ne yapar?

Hesap Makinesi ve Not Defteri her zaman açıktır; diğer uygulamalar kullanıcı "PC izin ver" diyene kadar kapalıdır (uygulama başına tek seferlik, kullanıcıya özel, "PC izni kaldır <uygulama>" ile geri alınır). Terminal, kod editörü, tarayıcı, şifre yöneticisi ve Jarvis penceresi hiçbir izinle açılmaz.

Eski kapsam notu: Not Defteri'nde yalnız adsız veya `.txt` belgenin metin alanına yazılabilir; dosya adı alanları, açma ve kaydetme işlemleri çalıştırılmaz. Metni kullanıcı kendisi kaydeder. Tarayıcı işleri mevcut tarayıcı motorundan yürür. Diğer uygulamalar için güvenilir hedef tanıma ve işlem desteği ayrıca eklenmelidir.

Windows erişilebilirlik ağacından görünür kontrol adlarını, gerçek kimliklerini, kullanılabilen işlem türlerini ve okunabilir değerlerini alır. Model tek adım seçer. Kontrol kimliği, pencere işlemi ve güncel içerik tekrar kontrol edilir. UIA doğrudan seçilen kontrole gider; pencereyi öne getirme zorunluluğu ve genel fare/klavye girdisi yoktur. Ardından yerel `InvokePattern`, `ValuePattern`, `SelectionItemPattern` veya `TogglePattern` kullanılır.

Fare koordinatı tahmin edilmez; rastgele tuş veya terminal komutu çalıştırılmaz. Bu sürüm model için ekranın erişilebilirlik kontrol ağacını okur; yeni bir ekran görüntüsüyle tıklama motoru eklemez. Grafik/oyun tuvali veya erişilebilirlik kontrolü sunmayan arayüzlerde işlem yapılamaz.

Yazılan metin aynı alandan birebir geri okunmalıdır. Düğme/seçim işlemi yeni görünür ad/değer veya belirli kontrolün beklenen durumu ile doğrulanır. Zaten var olan bir düğme etiketi, yeni işlem sonucu sayılmaz. Sonuç görülmezse işlem tekrar gönderilmez; durum `waiting` kalır. Devam komutu önce eksik sonucu kontrol eder. Kesintiden önce gönderilmiş olabilecek işlem tekrar oynatılmaz.

Sonuç kanıtı olarak kontrol adı okunurken görünmez karakterler ve boşluk farkları (sonda boşluk, NBSP, çift boşluk) sonucu bozmaz; metnin kendisi yine kesin aranır. Yazılan metin (`value`) birebir okunmaya devam eder.

Hesap Makinesi'nde Jarvis, planın beklediği ekran sayısını göndermeden önce hedefindeki sayılarla karşılaştırır: "15 ile 5 topla" için 19 ya da 194 yazdıracak bir adım reddedilir ve yeni plan istenir. 15, 5 ve 20 gibi hedefle açıklanan sayılar geçer. "Çıkan sonucu 3 ile çarp" gibi ekrandaki sayıya bağlı hedeflerde ve sayı sözcüğü içeren hedeflerde bu denetim kapalıdır.

Görev başlarken ekranda önceki işlemden kalan bir sayı varsa (örneğin 19) Jarvis önce "C" ile temizler ve ekranın 0 olduğunu doğrular, sonra rakamlara başlar. "Çıkan sonucu 3 ile çarp" gibi ekrandaki sayıya bağlı hedeflerde temizlemez. Temizleme doğrulanamazsa görev durur ve hiçbir rakama basılmaz.

Rakam düğmesine basan bir adımın beklediği ekran, düğmenin gerçekten üreteceği değerle de karşılaştırılır: ekranda 1 varken 7 tuşu ekranı 7 değil 17 yapar; plan 7 beklerse adım gönderilmeden reddedilir.

Basit Hesap Makinesi işleri ("12 ile 7 topla", "20 ile 4 böl", "15'ten 5 çıkar", "6 x 7") modele sorulmadan tuş tuş yürütülür ve ekrandaki sonuç okunarak doğrulanır; üç haneye kadar tam sayılarla, tam sayı ve negatif olmayan sonuç veren işlemlerde çalışır. Diğer görevler modele gider.

Geçersiz model planı en fazla üç kez hata bilgisiyle yeniden planlanır. Her tur en fazla 12, tüm görev en fazla 50 işlem adımı vardır. Hedef, sonuç beklentisi ve geçmiş kullanıcıya özel yerel görev kaydında tutulur. Yeniden açılışta devam etmek yeni pencere ve işlem kimliği doğrulaması gerektirir.

## Şifre ve işlem sınırları

Şifre/API anahtarı alanları modele gönderilmeden maskelenir ve doldurulmaz. Terminal, kaynak kod editörü, Jarvis kaynak dosyası, sistem yönetimi, ödeme/yayınlama/gönderme düğmeleri masaüstü aracına kapalıdır. Kaynak kod değişiklikleri önceki şifreli geliştirme, taslak testleri ve açık uygulama onayı yolunda kalır.

Silme, kaydetme/onay düğmeleri, mevcut alan metnini değiştirme ve toggle işlemleri somut önizleme bekler. Diğer görünür ve desteklenen kontroller, açıkça verilen görevin kapsamında çalıştırılabilir. Aynı fiziksel masaüstünde eşzamanlı ikinci görev başlatılmaz. Telefon ve aktif PC kullanıcısından farklı kullanıcı bu işlem akışını başlatamaz.

## PC'de doğrulama

Önce Hesap Makinesi örneğini dene. Ekranda gerçek 19 sonucu ve sohbetin doğrulama adımları görünmelidir. Sonra açık bir uygulamadaki uygun metin alanında kısa, hassas olmayan bir metin dene. `ValuePattern` sunmayan alanlar desteklenmez; otomatik klavye/pano yedeği yoktur. Bazı modern metin editörleri bu nedenle yazma aracıyla çalışmayabilir.

Görev sırasında başka pencereye geç: native UIA işlemi hâlâ yalnız seçilen hedefe gitmelidir; başka pencereye fare/klavye gönderilmez. Hedefi kapat veya kontrolünü değiştir: eski kontrol üzerinde işlem devam etmemelidir. Onay önizlemesinden sonra hedef içeriğini değiştir: eski onay uygulanmamalıdır. Doğrulanmamış işlemi `PC görevi devam` ile sürdür: aynı düğmeye tekrar basılmamalıdır. Geliştirme modunun çıkış/yeniden açılış şifre kontrolünü de dene.

Otomatik testlerde OS/UIA ve model davranışı taklit edilmiştir. Gerçek Windows PowerShell/UI Automation çalışması ve canlı modelin farklı uygulamalardaki plan doğruluğu bu ortamda denenmedi. Bu sürüm sınırsız uygulama kontrolü veya her işi bitirme garantisi değildir; üçüncü taraf proje klasörlerinde geliştirme yeteneği ayrıca yapılacak iştir.
