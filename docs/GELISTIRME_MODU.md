# Jarvis ile birlikte geliştirme

Jarvis'i kapat, paketteki Jarvis klasörünün içeriğini mevcut kurulumun üzerine kopyala ve `baslat.bat` ile aç. Mevcut kullanıcı verileri ve API anahtarları kurulum klasörünün dışında kalır.

## Başlama

Sohbet ekranında **Şifre Korumalı Geliştirme Modu** düğmesine bas. İlk girişte en az 6 karakterlik bir şifre oluştur; sonraki girişlerde aynı şifre kullanılır. Şifre yalnız maskeli giriş penceresine yazılır; sohbet geçmişine ve model istemine gönderilmez. Şifre değişimi geliştirme satırındaki **Şifre** düğmesindedir. Jarvis yeniden açıldığında alan kilitlenir.

İstediğini doğal şekilde anlat: “Şu menüyü sadeleştir”, “Mikrofon kapanınca bu davranışı düzelt”, “Önce dosyaları incele, sonra çöz”, “Bu tasarımdan devam edelim”. Sesli komutlar da aynı geliştirme motoruna gider.

**Görsel / Dosya** ile ekran görüntüsü, fotoğraf, tasarım veya belge ekle ve ne istediğini yaz. Ekler kendi geliştirme klasörüne kopyalanır; asıl dosya taşınsa bile referans korunur. PDF, DOCX, XLSX ve metin dosyaları içerik referansı olabilir. Görsel analizi için seçili sağlayıcının görsel destekleyen modeli gerekir. Gizli modda görsel buluta gönderilmez.

## Birlikte çalışma

Motor proje dosyalarını listeler, arar, satır aralığıyla okur ve gerçek içerik üzerinde düzenleme taslağı hazırlar. Büyük dosyalar parça değiştirilerek düzenlenebilir. Bir sonraki mesajda “bunu değiştir” dediğinde mevcut taslağı ve geliştirme bağlamını kullanır. Önceki konuşmalar ayrıca aranabilir; proje kararları ve bekleyen işler ayrı hafızada tutulur.

Değişiklik farkları sohbette gösterilir. Şifreyle giriş yalnız alanı açar; uygulama onayı değildir. Her taslak için **Uygula** veya “değişiklikleri uygula” ile son onay gerekir. Otomatik uygulama kaldırıldı; eski ayardaki açık değer de yok sayılır.

Her uygulamadan önce taslak ayrı geçici proje kopyasında, kullanıcı verisinden ayrı test edilir. Test bittikten sonra kaynak sürümü tekrar kontrol edilir ve yalnız değişen dosyaların yedeği alınır. Test başarısızsa asıl kaynak değişmez; dosya uygulama/kayıt hatasında yedekten geri dönülür. `baslat.bat` üzerinden açılışta yarım işlem kurtarılır ve yeni sürümün motor/web hazır sinyalleri doğrulanır. Başarısız açılışta önceki kaynaklar ve Python ortamı geri yüklenir. Sonradan elle değişmiş dosyalar ezilmez.

Ayrıntılar ve saklama sınırları: [Güvenli geliştirme](GUVENLI_GELISTIRME_20261008.md).

Başarılı değişikliklerin çalışan uygulamaya yüklenmesi için Jarvis'i yeniden başlat. **Geri Al** veya “son geliştirmeyi geri al” son uygulamayı geri getirir. Yeniden başlatmada şifre tekrar istenir.

## Görseller ve dosyalar

Yazılı tariften SVG arayüz taslağı/şema oluşturabilir, görsel referansı inceleyip tasarım ve kod hazırlayabilir. SVG dosyası, sohbet önizlemesi ve eski sürümler saklanır. “Son görseli göster”, “görsellerimi listele”, “ilk tasarıma dönüp yazıyı değiştir” gibi takip istekleri desteklenir. Yeni sohbet veya ekran yenileme dosyayı silmez. Masaüstü ve telefon sohbeti kayıtlı resimleri tekrar gösterir.

**Dosyaları Al** hazırlanmış kodu, görselleri ve referansları Belgeler > Jarvis Dosyaları > Jarvis Geliştirme altına dışa aktarır. Geliştirme şifresinin kaydı dışa aktarılmaz.

“Normal sohbete dön” modu kapatır ve kilitler; taslakları saklar. “Taslağı iptal et” yalnız bekleyen kod değişikliklerini kaldırır. “Geliştirme geçmişini temizle” geliştirme konuşma bağlamını ve karar hafızasını temizler; dosyaları silmez.

## Model ve doğrulama

Mevcut seçili sağlayıcı/API anahtarı kullanılır; bu mod ücretli sağlayıcıya otomatik geçmez. Ayrı ücretli servis veya yeni paket bağımlılığı eklenmedi. Bir geliştirme isteği birden fazla model çağrısı kullanabilir; ücretsiz sağlayıcıların mevcut kotaları geçerlidir. Kod/görsel kalitesi seçili modele bağlıdır.

Bu sürüm fotoğraf üreten bir görsel modeli eklemez; üretilen tasarım önizlemeleri SVG'dir. Mevcut Jarvis projesinin metin kaynaklarını düzenler; modelin yazdığı rastgele terminal komutlarını çalıştıran bir araç sunmaz. Kod değişiklikleri ve test yürütme, şifreli alanın uygulama akışındadır. GitHub yayını mevcut açık kullanıcı komutuyla yapılır.

Linux doğrulaması: 229 Python testi, 228 başarılı ve 1 Windows DPAPI testi atlandı; 5 motor bütünleşme denemesi ve 7 JavaScript grubu başarılı. Modeller ve donanım testlerde taklit edildi. Canlı API, gerçek Windows mikrofonu ve modelin farklı görevlerdeki başarısı bu doğrulamanın kapsamına dahil değildir.
