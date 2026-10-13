# Komut yürütme düzeltmeleri — 11 Ekim 2026

Bu değişiklik güncel GitHub `main` koduyla birleştirilmiştir. Mevcut Jarvis araçlarının yürütme, bağlam ve sonuç bildirimini düzeltir.

## Kurulum

1. PR birleştirildikten sonra mevcut GitHub güncelleme akışını kullan. Yerelde farklı kaynaklar varsa önce yedekle.
2. Güncellemenin aday testleri geçmesini bekle.
3. `run_tests.bat` ile kendi ortamında testleri çalıştır. Ardından `baslat.bat` ile aç.

Kullanıcı ayarı, API anahtarı veya geliştirme şifresi depoya eklenmez. Yeni bağımlılık eklenmedi. Android ve web arayüzü bu değişiklikte düzenlenmedi. Geri dönmek için mevcut güncelleme yedeğini kullan.

## Yeni davranışlar

- Açma/kapatma adımları dolu bir metin döndüğü için başarılı sayılmaz. `ApplicationResult.ok` açık pencere kanıtına göre belirlenir.
- Başlatma komutu hata verirse hata bildirilir. Komut gönderilmiş ama pencere doğrulanmamışsa açıkça bu durum söylenir. Tarayıcı sekmesindeki uygulama adı, o uygulamanın çalıştığının kanıtı sayılmaz.
- Benzer uygulama adları kullanıcıya seçtirilir. Birden fazla olası eşleşmeden rastgele uygulama açılmaz. Seçim 120 saniye boyunca yalnız ilgili kullanıcının oturumunda saklanır.
- `Krom` ve `notdefteri` gibi adlar tanınır. Diğer uygulamalar mevcut Başlat menüsü/kısayol taramasıyla bulunur; tüm disk taraması eklenmedi.
- `Onu aç` gibi göndermeler uygulama adı olarak aranmak yerine bağlamlı yönlendirmeye gider. Yönlendirici son iki saatten en fazla altı konuşma satırını, önceki komutu ve bekleyen soruyu alır; hassas bilgiler temizlenir.
- Çözülemeyen işlem komutu veya bozuk model JSON'u, işlem yapıyormuş gibi bir sohbet cevabına dönüştürülmez; netleştirme sorusu gösterilir.
- Araştırma, web görevi ve rapor kaydetme istekleri, model doğru niyeti seçtiğinde mevcut görev motoruna `görev:` öneki olmadan ulaşabilir. Görev motorunun araştırma/tarayıcı/yazma/geliştirme sınırları ve mevcut onayları korunur.
- Çok adımlı komutta uygulama adımı doğrulanamazsa veya seçim bekliyorsa sonraki adımlar çalıştırılmaz.

## Şifreli geliştirme

- Şifre koruması, kullanıcı ayrımı, yeniden açılışta kilitleme, taslak uygulama onayı ve geri alma korunur.
- Model `test` aracıyla hazırladığı taslağı ayrı proje kopyasında sınayabilir. Hata günlüğünü görüp düzenleyerek tekrar test edebilir. Tur başına en fazla üç test vardır.
- Kod taslağıyla turu bitirmek istediğinde güncel test kanıtı yoksa test çalıştırılır. Test başarısızlığında model düzeltme için sonucu alır. Üç başarısız denemeden sonra başarısızlık durumuyla taslak saklanır.
- `Taslağı test et` / `geliştirmeyi test et` kullanıcı komutları da aynı ayrı-kopya testini çalıştırır.
- Sonuçta kaç dosyada taslak olduğu, güncel testin geçip geçmediği ve değişikliklerin kaynaklara uygulanmadığı sistem tarafından belirtilir. Taslak değişirse eski test geçersiz olur.
- Taslak testinden sonra da kaynak dosyaları değişmez. Uygulamak için mevcut `değişiklikleri uygula` komutu gerekir; uygulama akışı aday testini yeniden çalıştırır.
- Bağımlılık dosyası değişikliği normal taslak testiyle başarı ilan edilmez; ayrı ortam kuran mevcut açık uygulama akışı gereklidir.
- Başarısız kod taslağı, görev ajanında tamamlandı olarak kapatılmaz.

## PC'de deneme

### Gemini 3.6 Flash

Model adı `gemini-3.6-flash` olarak kullanıcıya özel ana model alanına yazılabilir; mevcut `user_models` ayarı bu adı kabul eder, yeni API entegrasyonu gerekmez. Kaydettikten sonra Ayarlar'daki model kontrolünü çalıştır. Hesabın erişimi ve kotası canlı denemeyle doğrulanır. Mevcut ana model/yedek tercihleri bu PR ile otomatik değiştirilmez.

Google'ın resmî sayfasında standart API için ücretsiz katman listelenir. Ücretli faturalama kapalı tercihini koru; arama grounding gibi ek araçların koşulları farklıdır. Bu model Live API desteklemez; sesli canlı model ayarını bununla değiştirme. Kaynaklar: https://ai.google.dev/gemini-api/docs/models/gemini-3.6-flash ve https://ai.google.dev/gemini-api/docs/pricing (11 Ekim 2026 kontrolü).

1. `Paint aç` — Paint penceresi görünmeli ve doğrulama mesajı gelmeli.
2. Bilerek olmayan bir uygulama adı söyle — hata veya benzer ad seçenekleri gelmeli, tamamlandı görünmemeli.
3. Birden fazla benzer uygulama varsa kısa adını söyle, ardından seçenek numarasını gönder.
4. Paint hakkında konuş, ardından `onu aç` de — önceki hedef yönlendirmede kullanılmalı.
5. `Önce olmayan-program aç sonra Paint aç` de — ilk adım doğrulanmazsa ikinci adım çalışmamalı.
6. Şifreyle geliştirme moduna gir; küçük ve belirli bir kod düzeltmesi iste. Taslak farkı, test durumu ve uygulanmadığı bilgisi görünmeli.
7. `Normal sohbete dön`, ardından `geliştirmeyi test et` de — kapalı/kilitli alanın testi çalışmamalı.

Canlı modelin doğru hedefi seçmesi ve gerçek Windows pencerelerini tanıması bu ortamda doğrulanmadı. Otomatik testler model/OS davranışını taklit eder. Bu paket her yazılımı kontrol etme, herhangi bir terminal komutunu çalıştırma veya tüm görevleri bitirme garantisi vermez. Tanınmayan işlemde belirsizlik ve araç sınırları görünür kalmalıdır.
