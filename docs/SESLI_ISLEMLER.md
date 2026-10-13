# Sesli işlemler ve PC kontrolü · 7 Ekim 2026

Bu paket, geliştirme atölyesi kaldırılmış sürüme sesli işlem kataloğu ekler. Jarvis kaynak kodunu kendisi değiştirmez.

## Kurulum

Jarvis'i kapat. ZIP içindeki **Jarvis** klasörünün içeriğini mevcut Jarvis kurulumunun üzerine kopyala. `baslat.bat` ile aç. Kişisel `.jarvis` verilerini silme. Eski geliştirme atölyesi dosyalarını temizleyen önceki kurulum adımı korunmuştur.

## Uyandırma ve mikrofon

Yeni kurulumda varsayılan uyandırma adı Jarvis'tir. Önceden kaydettiğin isim korunur. Eski kurulumda **“Hey Jarvis uyandırmasını aç”** komutunu yazabilir veya mevcut uyandırma adınla seslenip söyleyebilirsin. Bu işlem ayar ekranıyla aynı kaydetme yolunu kullanır; mikrofonu açmaz. Ayarlar → Ses bölümünden de uyandırma adını Jarvis yapabilirsin.

**“Mikrofonu kapat”** fiziksel dinleme anahtarını kapatır. Mikrofon kapalıyken seslenerek açılmaz; mikrofon düğmesiyle aç veya **“Mikrofonu aç”** yaz. Başka işlemler bu bayrağı değiştirmez.

Yerel Hey Jarvis dinleyicisinin kurulması gerekir. Hazırlanması veya yüklenmesi başarısızsa mevcut uyandırma yöntemi kullanılır; ayar kaydetme yanıtı bunu bildirir. Uyandırma sözcüğünün yerel algılanması, konuşma tanıma ve yapay zekâ işlemlerinin tamamının internetsiz çalıştığı anlamına gelmez.

## Ortak işlem kataloğu

77 kayıtlı işlem; görev, not, takvim, hafıza, bilgi tabanı (belge ekle; silme onaylı), çalışma kaynakları, alıştırma ve deneme, ses/dinleme/görünüm ayarları, dosyalar, sağlayıcı durumu, GitHub durum kontrolü (yalnız okuma) ve PC pencerelerini kapsar. GitHub'a yükleme/alma, telefon erişimini açma, anahtar ve güvenlik izinleri sesle kapalıdır; ilgili ayar sayfası düğmesinden yapılır. Sesli komutlar arayüzün kullandığı gerçek Bridge işlevlerini çağırır. Yapay zekâ serbest Python metodu veya shell komutu çalıştıramaz; kayıtlı işlem adı ve parametreleri doğrulanır.

Örnekler:

- “Notlarımı listele.”
- “Pompa bakımı görevini sil.” — İlgili kaydı bulur, silmeden önce onay ister.
- “Temayı açık yap.”
- “Uyandırma kelimesini Jarvis yap.”
- “Dinleme bittikten sonra 60 saniye açık kal.”
- “Ses seçeneklerini listele.”
- “Çalışma modunu aç.”
- “Deneme sınavı başlat, 15 soru olsun.”
- “Öğrenmeyi kapat.”
- “Açık pencereleri listele.”
- “Chrome penceresini öne getir.”
- “Word penceresini büyüt.”
- “Chrome'da yeni sekme aç.”
- “Word penceresinde kaydet kısayolunu gönder.”

Komutun açık olması yeterlidir; her ifade için ayrı sabit bir cümle ezberlemek gerekmez. Yorumlama mevcut yapay zekâ sağlayıcısıyla yapılır ve yanlış yorumlama ihtimali vardır. Eksik hedef için soru sorulur; soru ve asıl istek takip eden yanıta taşınır. Silme, geçmiş temizleme, yeniden başlatma ve sağlayıcı/model değiştirme işlemleri 90 saniyelik kullanıcıya ait onay bekler. Başka komut eski onayı iptal eder. Ücretli sağlayıcıya otomatik geçiş eklenmemiştir.

Anahtar girme, oturum açma ve güvenlik izni verme gibi işlemler ilgili güvenli arayüz üzerinden yapılır. Yeni katalog her üçüncü taraf uygulamanın bütün işlemlerini destekleyen genel bir masaüstü ajanı değildir.

## PC işlemleri

Windows görünür pencereleri uygulama adı veya başlıkla eşleştirir. Aynı uygulamanın birkaç penceresi varsa başlığı sorar. Pencerenin gerçekten öne gelip gelmediği veya küçülüp büyüdüğü işletim sisteminden kontrol edilir; engellenen işlem başarılı diye bildirilmez.

Desteklenen hedefli kısayollar: yeni/sonraki/önceki sekme, bul, kaydet, kopyala, yapıştır, tümünü seç, geri al ve yinele. Klavye işlemi öncesinde hedefin hâlâ önde olduğu doğrulanır. Yanıt kısayolun gönderildiğini bildirir; uygulamanın örneğin dosyayı gerçekten kaydettiğini iddia etmez. Genel koordinat tıklama ve serbest komut çalıştırma eklenmemiştir.

## Doğrulama

Yeni işlem testleri ve gerçek Bridge ile yapılan başsız bütünleşme denemesi geçti. Bunlar tip/alan doğrulama, bilinmeyen işlem reddi, kullanıcı ayrımı, silme/onay/iptal/süre aşımı, kaybolmuş kayıt, mikrofonun kapalı kalması, tema kaydı, çoklu pencere belirsizliği, odak kaybı ve başarısız pencere değişimini kapsar. Beş mevcut JavaScript davranış grubu da geçti.

Linux test ortamındaki genel Python çalıştırması: 188 test, 6 hata, başarısız assertion yok. Bu 6 hata önceki pakette de bulunan Windows yazı tipi/DPAPI ve ortamın ağ arayüzü erişimi sınırlamalarıyla ilgilidir. Gerçek Windows mikrofonu, Hey Jarvis algılaması ve pencere tuş gönderimi bu ortamda donanımla doğrulanmadı.
