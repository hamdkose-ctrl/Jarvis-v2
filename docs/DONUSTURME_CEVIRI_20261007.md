# Belge dönüştürme ve Türkçe çeviri düzeltmeleri

## Kullanım

Dosyalar sayfasında PDF, Word, Excel veya metin dosyasını seç. **Türkçeye Çevir** düğmesi hedef dili açıkça Türkçe olarak seçer. Word dosyalarında İngilizce düğmesi de ayrı durur. Sohbette `dosyayı turkceye cevir` yazımı da desteklenir.

Word ve PDF çevirileri önce sohbet ekranına gelir. Sonucu dosya olarak almak için **çıktı al** de. Excel çevirisi yeni bir çalışma kitabı kaydeder; sayılar ve formüller çevrilmez. Kaydetme penceresinde kaynak dosyadan farklı bir ad seç.

Format değiştirmek için `PDF dosyasını Excel'e dönüştür`, `Word dosyasını PDF formatına dönüştür` gibi komutlar veya dosya işlem düğmeleri kullanılabilir. Dil çevirisi format dönüştürmesinden önce ayrılır.

## Dönüşüm davranışı

- PDF → Excel: metin sayfalara ayrılır ve özgün sayfa görüntüleri **Kaynak sayfalar** sekmesine eklenir. Ders başlıkları ve cevap anahtarı olan tanınabilir soru kitapçıklarında ayrıca **Sorular** sekmesi oluşur: ders, soru no, soru, A/B/C/D, doğru cevap, PDF sayfası ve kontrol notu.
- Verilen `Sorular 2023.pdf`: 48 ders, 528 soru, kaynak anahtarından eşleşen 528 cevap ve 51 sayfa görüntüsü. 88 soruda şekil, formül veya özel yazı kontrol notu var. Bir sorunun metin olarak okunamayan seçeneği de işaretli. Görsel içerik tahmin edilmez; kaynak görünümü esas alınır.
- PDF → Word: sayfa görüntüleri korunur; bu çıktıdaki metin düzenlenebilir değildir. Şekil, formül ve sağdan sola yazı için düzeni koruyan aktarım kullanılır.
- Word → Excel/PDF: paragraf ve tablo sırası, başlıklar ve normal gömülü görseller aktarılır. Birleşik hücreler açılır; tema ve özgün sayfa düzeni birebir taşınmaz.
- Excel → Word/PDF: sayfalar, tablo hücreleri ve normal gömülü görseller aktarılır. Formüller yeniden hesaplanmaz; kayıtlı sonuç yoksa formül açıkça gösterilir. Grafik ve hücre stilleri birebir taşınmaz.
- TXT/MD: başlık, paragraf ve Markdown tabloları ayrı belge öğeleri olarak aktarılır. CSV'de normal tam sayı ve noktalı ondalıklar sayısal hücreye dönüşür; başında sıfır olan kodlar metin kalır.
- Aynı biçimde kopyalama kaynak dosyanın bütün baytlarını korur. Eski DOC/XLS kaynaklar açık bir hata verir; önce DOCX/XLSX olarak kaydedilmelidir.

## Çeviri ve kayıt güvenilirliği

Uzun metinler kelime/satır sınırlarında yaklaşık 3500 karakterlik bölümlere ayrılır ve 8000 çıktı tokenı bütçesiyle çevrilir. Çevirinin etkin isteğine, bölüm sayısına göre en fazla 30 dakikalık süre tanınır; iptal edilen veya süresi dolan istek yeniden etkinleştirilmez. Zorunlu son `NOTLAR:` bölümü gelmezse sonuç eksik kabul edilir ve kaydedilmez. Bu kontrol modelin her cümleyi doğru çevirdiğini garanti etmez; sessizce kesilmiş cevapların kaydedilmesini önler.

Excel çevirisinde boş, eksik veya yinelenen hücre sonuçları reddedilir. Kaynak metin ve çevrilen hücre metni formüle dönüştürülmez. Dönüştürme ve çeviri önce geçici dosyaya yazılır; hata olursa mevcut çıktı korunur.

## Doğrulama

157 Python testi, iki gerçek modül entegrasyonu ve beş JavaScript test grubu geçti. Kaynak PDF'nin özeti değişmedi; örnek Excel'de 529 satır (başlık dahil), 48 ders, 528 cevap ve 51 gömülü sayfa görüntüsü doğrulandı. Excel ve üretilen örnek PDF görsel olarak kontrol edildi; Türkçe karakterler okunuyor.

Seçili kullanıcı/Gemini bağlantısında `The pump must be inspected tomorrow.` cümlesi gerçek istekle Türkçeye çevrildi: `Pompanın yarın kontrol edilmesi gerekiyor.`

Word çıktılarında tablo, resim ve sayfa sonu öğeleri dosya düzeyinde test edildi. Bu bilgisayardaki belge önizleme ortamında LibreOffice bulunmadığından DOCX'in son sayfa yerleşimi görsel olarak doğrulanamadı; Word'de açılarak kontrol edilmeli.

PDF sayfa okuma/görüntüleme için kilitli bağımlılık: `pypdfium2==5.13.0`. Özgün kullanıcı PDF/Excel dosyaları değiştirilmedi.
