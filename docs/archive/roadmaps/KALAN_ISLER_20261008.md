# Kalan Kod İşleri — 8 Ekim 2026

Önceki bütün yerel kontrol paketlerinin düzeltmeleri bu pakete dahildir. Son ayrıntılı rapordaki matematik denetimi ve GitHub güncelleme güvenliği işleri bu turda işlendi. GitHub'a yükleme veya uzak main ile birleştirme yapılmadı. Önceki raporlar kendi paketlerinin tarihsel sonuçlarıdır; güncel davranış bu belgededir.

## Matematik: Bağımsız Hesap Kontrolü

`modules/math_verifier.py`, model çıktısını çalıştırmadan sınırlı AST ve tam kesir aritmetiği kullanır. Toplama, çıkarma, çarpma, bölme, sınırlı tam sayı üsleri, parantez, ondalık sayılar, temel LaTeX kesirleri ve modelin verilenler alanındaki sayısal değişkenler desteklenir. İşlem derinliği, boyutu ve üsleri sınırlandırılır; kod çağrıları, attribute erişimi ve keyfi fonksiyonlar çalıştırılmaz.

İşlem eşitlikleri tek tek kontrol edilir. Tam çözümde verilen ifade hesaplanabiliyorsa nihai sonuç da o ifadeyle karşılaştırılır. Örneğin x=2, y=-1 için pay 3 ve nihai kesir sonucu 1 ayrı ayrı denetlenir; payı nihai cevap olarak vermek kabul edilmez. Sayısal sonuç olarak sunulan sıfıra bölme de reddedilir.

Hatalı hesap çıktığında modelden aynı soru/kapsam için yalnız bir düzeltme istenir. İkinci cevap da hesapta çelişiyorsa hata döner; yanlış yeni çözüm gösterilmez ve yeni matematik konuşma/ilerleme kaydı oluşturulmaz. Desteklenen doğru işlemler ve doğrulanamayan adımlar ayrı sayılır. Kontrol sonucu hem metne hem çalışma alanına eklenir ve konuşma geçmişinde saklanır. Eski sonuçlar, denetim kaydı yoksa doğrulanmış gösterilmez.

Bu bir genel sembolik matematik ispat sistemi değildir. Trigonometri, genel denklem çözümü, geometri gerekçeleri veya her olası LaTeX biçimi doğrulanmış sayılmaz. Modelin görseldeki sayıları veya soruyu doğru okumasını bu denetim tek başına kanıtlayamaz. Denetim, okunmuş verilenlerle yapılan desteklenen hesapları sınar. “Çöz” denmedikçe açıklama/ara adım kapsamı korunur; seçili alandaki ara sonuç tüm sorunun cevabıyla karşılaştırılmaz.

## GitHub Güncellemesi: Aynı Güvenli Sürüm Akışı

Güncelleme hâlâ yalnız açık kullanıcı isteğiyle kurulur. Yerel yayınlanmamış değişiklikler ve bekleyen geliştirme kaydı varsa kurulmaz.

1. Değişen/silinen kaynak ve görsellerin tam listesi hazırlanır; sembolik bağlantı ve proje dışı hedeflere yazılmaz.
2. Güncelleme ayrı kaynak kopyasına uygulanır. Bağımlılık dosyası değişirse ayrı aday Python ortamı hazırlanır; mevcut `.venv` değiştirilmez.
3. Mevcut güvenilir regresyon testleri aday kaynakla çalışır; aday testleri değişmişse onlar da ayrıca çalışır. Node.js ve zorunlu testler eksikse kurulum ilerlemez.
4. Test sırasında değişen asıl dosyalar tekrar kontrol edilir. Değişiklik varsa elle yapılan çalışma korunur.
5. Dosyaların önceki baytları, Python yolu ve eski güncelleme/sürüm bilgisi kalıcı kurtarma kaydına yazılmadan çalışan kaynağa dokunulmaz.
6. Başarılı uygulama açılış onayı bekler. `baslat.bat`/`launcher.py` üzerinden yeniden başlatmada motor ve web hazır sinyalleri birlikte beklenir; başarısız açılışta kaynak, görsel, Python yolu ve güncelleme SHA bilgisi geri döner.

Kurtarma/test altyapısını değiştiren GitHub güncellemeleri otomatik uygulama yolunda reddedilir. Böyle bir altyapı geçişi test edilmiş tam kaynak paketiyle yapılmalıdır; bu koruma kurtarma kodunun kendi kendisini geçersiz hale getirmesini önler. Yerel değişikliklerin üzerine güncelleme kurmak veya GitHub'a yüklemek bu çalışma kapsamında yapılmadı.

Kaynak yedekleri mevcut değişen dosya/görsel baytlarıyla tutulur; aynı kaynak-yedek geçmiş sınırları uygulanır. Bağımlılık ortamlarının boyutu kaynak-yedek boyutundan ayrıdır. Kullanılmayan aday ortamlar geçmiş temizliğinde kaldırılır. Kaynak geri alma, yeni sürümün gerçek kullanımda değiştirdiği tüm kişisel veri şemalarını otomatik geri çeviren bir veri göçü sistemi değildir.

## Onaylanmış Sürümün Sonradan Geri Alınması

Açılışı onaylanmış sürümün bekleyen işlem işaretçisi temizlenmiş olur. Sonradan geri alma başlarken bu işaretçi yeniden yazılır; ilk dosya değişiminden önce işlem `rolling_back` olarak kaydedilir. Geri alma yarıda kesilirse sonraki güvenli açılış tamamlar. Başka bir bekleyen sürüm işlemi varsa onun işaretçisinin üzerine yazılmaz.

## Doğrulama

- 470 Python testi: 469 başarılı, Windows DPAPI gerektiren 1 test atlandı.
- JavaScript sözdizimi, 10 JavaScript davranış grubu ve 6 donanım/model taklitli entegrasyon grubu başarılı.
- 21 yeni Python testi: 11 matematik denetimi/gerçek tutor akışı, 8 güncelleme yaşam döngüsü, 2 onay sonrası geri alma testi. Çalışma alanının denetim sonucu ve yeniden yüklemesi için JavaScript kontrolleri de eklendi.
- Güncelleme testinde gerçek alt süreç kasıtlı açılış hatasıyla çalıştırıldı; eski GUI kaynakları ve güncelleme SHA'sı geri geldi. Ağ, pip kurulumları ve model cevapları testlerde taklit edildi; gerçek GitHub indirmesi, ücretli model çağrısı veya mesaj gönderimi yapılmadı.
- Tam log: `docs/MAIN_PAKET_TEST_SONUCU.txt`. ZIP kaynak hash'leri karşılaştırılır ve çıkarılan paket üzerinde aynı zorunlu doğrulama tekrar çalıştırılır.

## Bilgisayarında Doğrulanacak Kısım

Gerçek Windows/mikrofon/hoparlör bu ortamda yok. Bunlar yapılmış veya düzelmiş sayılmadı. Yeni bir seçenek/ayar eklenmedi.

Jarvis kapalıyken bu ZIP'teki Jarvis klasörünün içeriğini mevcut proje köküne aktar; kişisel ayarlarını, anahtarlarını ve `.venv` klasörünü koru. `baslat.bat` ile aç. Önceki ZIP'leri sırayla kurmana gerek yok.

1. İlk açılışta “Hey Jarvis merhaba” de. Görünen algılanmış metni ve cevabın gecikmesini kontrol et. Sesi değiştirip iki soru daha sor; aynı ses sürmeli.
2. Ses hazırlanırken Dur düğmesini kullan. Motor servis zaman aşımını beklemeden yeni komut almalı. Ekran alanı seçiminin iptalinde ve tamamlanmasında Jarvis penceresi geri gelmeli.
3. Matematikte x=2, y=-1 için `(x²+y³)/(x-y)` sorusunu “Çöz” diyerek dene: pay 3, payda 3, nihai cevap 1 olmalı. Hesap denetimi satırı görünmeli. Desteklenmeyen konular denetimden geçmiş gibi gösterilmemeli.
