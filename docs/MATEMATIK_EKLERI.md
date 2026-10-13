# Matematikte dosya, görsel ve açıklama

Çalışma → Matematik Modu içindeki Dosya / Görsel Yükle düğmesi veya bırakma
alanı tek dosyayı alır. Varsa yazılmış talimatla, yoksa soruyu ve yöntemi
anlatma isteğiyle otomatik olarak modele gönderir. Varsayılan davranış açıklamadır;
tam çözüm ve sonuç ancak öğrenci açıkça çöz dediğinde veya Çöz düğmesine bastığında
istenir. Öğrencinin sorduğu adım aynı soru bağlamında açıklanır.

Desteklenen ekler: PNG, JPG, WEBP, GIF, BMP, PDF, DOCX, TXT ve MD; en fazla 20 MB.
PDF'nin gösterilen özgün sayfası, taranmış sayfalar dahil, resim olarak incelenir.
Önceki/Sonraki Sayfa ile diğer sayfalara geçilir; istek aynı sayfaya dayanır. DOCX'in metni ve tabloları okunur; yalnız
gömülü resim içeren Word belgesi için sorunun fotoğrafını yüklemek gerekir.

Uygun olduğunda model sayı doğrusu, kesir, nokta grafiği veya üçgen şeması verisi
üretir. Sistem bu sınırlandırılmış veriyi SVG'ye çevirir; model kodu/SVG'si
çalıştırılmaz. Grafik verilen noktaları doğrularla birleştirir; üçgen ölçekli
değildir. Bozuk çizim açıklamayı düşürmez. explain_only talimatı görselin de sonucu
açığa çıkarmamasını ister; modelin bunu gerçekten uygulaması canlı model testi gerektirir.

Son ekin normalize edilmiş görüntüsü veya belge metni ve son sekiz konuşma turu
profilde saklanır. Takip sorusu için tekrar yükleme gerekmez. Yeni soru, matematik
bağlamını ve normalize edilmiş görüntüyü temizler; asıl yüklenen dosyayı silmez.
Yeni ek önceki normalize görüntüyü değiştirir; sürekli kopya biriktirilmez.

Otomatik testler veri akışını, çizim güvenliğini ve bağlam ayrımını doğrular.
Gerçek Gemini okuma doğruluğu ve matematik sonucunun doğruluğu otomatik testlerle
kanıtlanmış değildir; modelin kontrol açıklaması bağımsız hesaplama doğrulaması değildir.

## İşlem ekranı ve ara sonuç ayrımı

- İşlem adımları artık resim yerine formülleri biçimlendirilmiş kartlarda gösterilir.
  Verilenler ve incelenen ifade, her adımın hesabı ve kısa gerekçesi ayrıdır.
- Ara hesaplar **Ara işlem**, açık tam çözümde son adım **Sorunun cevabı** olarak
  etiketlenir. Tam cevap, anlatım kaydırılırken de üstte görünür. Payın 3 çıkması
  ile tüm kesrin 1 çıkması ayrı adımlardır; yalnız pay anlatıldığında bunun tam
  sorunun cevabı olmadığı belirtilir.
- Model, sınırlandırılmış `work` verisi üretir. İstek amacı ve alan kapsamı sunucuya
  aittir; modelin `final` etiketi açıklama/alan anlatımında nihai cevap etiketine
  dönüşmez. Veriler profilin konuşma turuyla kaydedilir, yeniden açılınca korunur.
- **Çöz** düğmesi eski alan seçimini göndermez; tam normalize edilmiş kaynakla
  güncel sorunun tamamını ister. **Seçili alanı anlat** kırpılmış alanla devam eder.
- Eski numaralı SVG işlem kartlarının yalnız metinleri okunup formülleri biçimlenir;
  eski SVG kodu sayfaya eklenmez. Desteklenen kesir, üs, kök, bölme/çarpma işaretleri
  HTML olarak gösterilir. İç içe süslü parantezli kesirler de desteklenir.
- Bozuk/eksik `work` verisi açıklamayı düşürmez. Tam çözümde son cevap belirtilmemişse
  tamamlanmış çözüm olarak işaretlenmez. Grafik/üçgen/sayı doğrusu görselleri korunur.

Testler 3 olan pay/3 olan payda/1 olan cevap ayrımını, yeniden açılmayı, alan seçiminin
Çöz'e taşınmamasını, eski çizimin dönüşümünü ve HTML kaçışını doğrular. Bu kontroller,
canlı modelin her matematik sorusunu doğru çözdüğünü veya Windows'ta görünümün
kullanıcı tarafından doğrulandığını göstermez.


## Özgün kaynak sayfası

PDF kaynaklarının özgün dosyası profil içinde bir kez saklanır. Sol önizleme gerçek
PDF sayfasından çizilir; metin çıkarımıyla sayfa yeniden dizilmez, sayfalar kolaj
yapılmaz. Sayfa en/boy oranı, sütunlar, şekiller ve formüller korunur; görüntü
yalnız panel boyutuna sığacak şekilde ölçeklenir. Görsel ekler de kaynak görüntüsü
olarak gösterilir, yapay zekâ tarafından yeniden çizilmez.

Alan seçimi özgün sayfanın kopyasından geçici olarak kırpılır; sol taraftaki sayfayı
değiştirmez. Çöz düğmesi, PDF'de o anda gösterilen sayfanın tamamını kullanır.
Genel Kaynaktan Çalış görünümündeki PDF seçimi de aynı sayfadan modele gönderilir.

Kaynak kaldırılınca özgün PDF kopyası da silinir; matematikte Yeni Soru veya yeni ek
eski normalize görüntü/PDF'yi temizler. Eski kayıtlarda özgün PDF bulunmuyorsa bunun
sayfa düzeni olmadığı belirtilir ve yeniden yükleme istenir. DOCX/TXT/MD'nin metin
önizlemesi özgün baskı düzenini korumaz; bu görünüm için PDF veya görsel gerekir.

Testler özgün PDF baytlarının değişmemesini, renk/en-boy oranını, çok sayfalı gezinme
verisini, aynı sayfadan kırpma/tam sayfa model akışını, profil ayrımını ve temizlemeyi
doğrular. Windows arayüzünde gerçek görsel kontrol ve canlı model doğruluğu ayrıca
doğrulanmış değildir.
