# JARVIS Çalışma Modu — v5

Çalışma Modu tüm kullanıcıların standart özelliğidir. Kullanıcılar aynı motoru kullanır ancak kaynaklar, mod seçimi, ilerleme kayıtları ve API anahtarları profil bazında ayrıdır.

## Modlar
- Kaynaktan Çalış: yalnız yüklenen kaynakların desteklediği içerikle yanıt verir.
- Öğretmen Modu: açıklar, örnekler ve uygun olduğunda tek bir kontrol sorusuyla ilerler.
- Sınav Modu: çözümü kullanıcı istemeden vermez; soru-cevap/değerlendirme odaklıdır.
- Matematik Modu: adım adım çözüm ve düzgün matematik sembolleri kullanır.
- Uygulamalı Mod: teori yerine örnek, hesap, kod, formül veya teknik uygulamaya ağırlık verir.

Kaynak aramasında belgenin tamamı her soruda modele gönderilmez; yalnız ilgili parçalar seçilir. Bu hem hız hem API tüketimi için önemlidir.

## Son 3 Yıl Çıkmış Soru Odağı
- Kitap/kaynaklar öğretim ve açıklama için ana bilgi kaynağıdır.
- Çıkmış soru dosyaları sınav yılı etiketiyle ayrı eklenir.
- Yüklenen çıkmış sorular içinden en yeni 3 yıl otomatik seçilir.
- Çalışma planı, konu önceliği ve soru tarzında varsayılan ağırlık %70 çıkmış sorular / %30 kitap-kaynaktır.
- Çıkmış soru metni resmi cevap anahtarı sayılmaz. Resmi cevap kaynakta açıkça yoksa JARVIS bunu resmi cevapmış gibi sunmaz.
- Daha eski soru dosyaları saklanabilir ancak son 3 yıl önceliğinin önüne geçmez.

## Son 3 yıl çıkmış soru analizi
- Çıkmış sorular yıl etiketiyle eklenir; en yeni üç sınav yılı esas alınır.
- İlk çalışma isteğinde analiz eskiyse JARVIS otomatik yeniler. İstenirse **Analiz Et / Güncelle** düğmesiyle elle de çalıştırılır.
- Analiz üç çıktı üretir: **en çok çıkan konular**, **yükselen konular**, **soru tipi dağılımı**.
- Çalışma planı ve deneme sorusu seçimi bu istatistiği öncelik sinyali olarak kullanır; öğretim/çözüm bilgisi kitap ve kaynaklara dayanır.
- Analiz, yüklenen soru metninin okunabilen kısmına dayanır. Metin çıkarımı eksikse güven seviyesi düşürülür; resmi cevap anahtarı yoksa doğru cevap uydurulmaz.

## Son 3 yıl + konu kilidi çalışma akışı
- Çıkmış soru yüklerken yıl zorunlu; dönem ve oturum isteğe bağlıdır. Aynı yılın farklı oturumları ayrı soru kaynağı olarak tutulur.
- Ana ekrandaki `Bugünkü Çalışmayı Başlat`, son 3 yıl soru ağırlığı ile kullanıcının konu başarısını birlikte değerlendirir.
- `Yanlışlarım` yanlış soruları tekrar döngüsüne alır; iki doğru tekrar öğrenilmiş kabul edilir.
- `Deneme` 10/20/tam seçenekleriyle gerçek çıkmış soru havuzundan deneme oluşturur ve konu bazlı sonuç verir.
- Konu anlatımı sırasında konu kilitlidir. Kullanıcı açıkça `sonraki konuya geç` veya `konuyu değiştir` demedikçe başka konuya geçilmez.
- Yeni eklenen PDF kitaplarda sayfa bilgisi korunur; uygun kaynak eşleşmelerinde `Kaynak: ... · Sayfa N` gösterilir.
