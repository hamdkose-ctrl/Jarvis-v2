# Jarvis düzeltmeleri ve genel tarama — 8 Ekim 2026

Hedef kurulum: `C:\Users\HmdKose\Desktop\Jarvis`.

## Uygulanan düzeltmeler

- Ayarlar ekranı, Yapay Zekâ/Bağlantılar alt sekmesinin eski seçimi yüzünden araçlar ekranını çiziyordu. Ayarlar artık kendi geçerli alt sekmesini açar. Anahtar kurulum ve bildirim kısayolları Araçlar içindeki bağlantı ekranına gider.
- “Çalışmaya başla” komutu çalışma ekranına özel bir başlangıç olayı gönderir. Arayüz seçili/bugünkü konunun gerçek ders anlatımını başlatır; kaynak modunda seçili kaynağı kullanır. Genel komut sohbetine yalnız konu adı üretmesi için bırakılmaz. Kullanıcı değişimi ve sayfadan çıkış denetlenir.
- PDF → Word: ana içerik doğal Word paragraflarıdır, soru ve seçenekler düzenlenebilir. Orijinal sayfa görüntüleri şekil/formül referansı için ayrı ek bölümde korunur. Görüntüler düzenlenebilir metin değildir. Taranmış, metin katmanı olmayan sayfalar için OCR uygulanmış gibi davranılmaz.
- PDF → Excel: mevcut ayrıntılı Sorular ve kaynak görüntüleri korunur. Ön tarafta Çalışma tablosu; çok satırlı soru/seçenekler, cevap girişi, seçenek doğrulaması, doğru/yanlış formülü, eksik cevap anahtarı durumu ve kaynak bağlantısı vardır. Orijinal kaynak dizeleri formüle çevrilmez.
- Günlük maskelemesi Groq `gsk_`, yeni GitHub `github_pat_` ve diğer GitHub token öneklerini kapsar. URL kullanıcı adı/şifresi, sorgu ve fragment bilgileri maskelenir.
- Windows DPAPI başarısızsa anahtar koruması base64'e sessizce düşmez; kayıt hata verir. Base64 kayıtları arayüzde şifreli gibi gösterilmez.
- Geliştirme modu kimlik doğrulanmış olsa bile komutla açılamaz. Manuel arayüz kapısı kullanılır. Otomatik uygulama kapalı ve son onay zorunludur.
- Geliştirme ekranında mikrofon tepsi/küçük pencere/web ortak yolundan da açılamaz. Ekrandan çıkış önceden kapalı mikrofonu kendiliğinden açmaz.
- Dosya listesi “Yenile” düğmesi artık gerçek önbellek atlaması yapar. Tarama sınırı tüm köklerde toplam 4000 dosyadır.
- Mesaj gönderme, geliştirme uygulama ve GitHub bağımlılık sabitleme hata yollarında kullanıcıya güvenli hata açıklaması eklenmiştir. Canlı mesaj gönderilmemiştir; GitHub'a yayın yapılmamıştır.

## Doğrulama

Hazırlanan kaynakta zorunlu ortak doğrulama çalıştırıldı: 288 Python testi, 287 başarılı / 1 atlandı; 6 JavaScript dosyasının sözdizimi; 10 JavaScript davranış grubu; 6 bütünleşme grubu başarılı.

Yeni testler Ayarlar/bağlantı yönlendirmesi, konu/kaynak başlangıcı, kalıcı geliştirme kapısı, mikrofon önceki durumu, zorunlu dosya yenileme, Windows koruma hatası ve sır maskelemesini kapsar. Çalışma başlatma olayı gerçek ana modül ile ayrıca sınandı.

2023 Excel: 528 soru, eski Sorular tablosuyla bütün hücreler birebir aynı. Yeni çalışma sayfası aynı sayıda kayıt içerir. 2024 Word: 480 soru, düzenlenebilir metin paragrafları ve 51 kaynak sayfa görüntüsü; düzenleme koruması bulunmuyor.

Word sayfa görüntüleme denemesi başarısız: paketlenmiş LibreOffice bu ortamda bulunamadı. Word sayfalarının son görsel yerleşimi doğrulanmış değildir. Metin ve dosya yapısı doğrulanmıştır. Gerçek Windows arayüzü, canlı model yanıtı, mikrofon/kamera ve telefon cihazı testlerin taklitlerinden farklı bir doğrulama gerektirir.

## Genel taramanın sınırı ve kalan işler

Tüm proje Python kaynakları derleme/sözdizimi taramasından, tüm webui JavaScript dosyaları sözdizimi kontrolünden geçirildi. Menü, çalışma, dönüşüm, hata günlüğü, geliştirme kapısı, dosya taraması, anahtar koruması ve ortak mikrofon yolları doğrudan kaynak üzerinde incelendi. Bu, her satırın bütün olası cihaz koşullarında hatasız olduğunun kanıtı değildir.

`main.py`/`nx.js` bölünmesi, açık bağımlılık enjeksiyonuna geçiş ve görü önizleme akışı bu düzeltme paketinde yeniden tasarlanmadı. Telefon tokenlarının saklama biçimi ve gerçek telefon HTTPS/mikrofon doğrulaması ayrı iş olarak duruyor. Bazı isteğe bağlı servisler geniş istisna yakalamalarını koruyor; sayı üzerinden otomatik silme yapılmadı.
