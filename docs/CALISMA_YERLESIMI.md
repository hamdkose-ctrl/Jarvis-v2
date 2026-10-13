# Kaynak ve anlatım yerleşimi

Çalış sekmesinde soru/kaynak solda, anlatım sağda görünür. Soru Çöz, Yanlışlarım,
Deneme ve Programım sekmeleri korunur. İlerleme/hedef ve kaynak/sınav analizi
üstteki İlerleme ve Kaynaklar sekmelerindedir; dar pencerede iki çalışma sütunu alt alta gelir.

Matematikte dosya yükleme mevcut açıklama akışını başlatır. Soldaki görselde
fareyle sürükleyip **Seçili alanı anlat** düğmesine basılır. Sunucu alanı
normalize edilmiş tam görüntüden kırpar ve yalnız kırpımı modele gönderir.
Tam görsel korunur. Görsel kimliği ve koordinatlar doğrulanır; eski/yabancı
profile ait seçim reddedilir. Seçili alan geçicidir; önizleme yenilenince yeniden
seçilir. Yeni soru önceki eki ve seçimi temizler.

PDF önizlemesi mevcut ilk dört sayfanın birleşik görselidir; sayfa gezgini değildir.
DOCX/TXT/MD ve kayıtlı çalışma kaynakları okunmuş metin olarak görünür (en fazla
50.000 karakter). Metinde bir kısmı işaretleyip **Seçili metni anlat** kullanılabilir
(seçili metnin ilk 5.000 karakteri açıklama isteğine eklenir).

Varsayılan işlem yalnız istenen kısmı/yöntemi anlatır. **Çöz** açık çözüm isteğidir.
Daha basit anlat ve sesli anlat kısayolları matematik alanında da bulunur.

Otomatik kontroller gerçek kırpım boyutunu, tam görselin korunmasını, profil
ayrımını, eski/geçersiz seçimleri ve açık çözüm isteğinin ayrı kalmasını doğrular.
Modelin matematik doğruluğu ve gerçek Windows üzerinde fare/ses akışı ayrıca
kullanımda doğrulanmalıdır.

## Görünüm ve alan kullanımı
Çalışma sayfası uygulamanın cam panel renklerini kullanır; ayrı koyu tema uygulanmaz.
Mod seçimi tek araç çubuğundadır. Yükleme alanı görselin altına taşınır; soru
ve Anlat/Çöz düğmeleri aynı satırdadır. Masaüstünde iki panelin yüksekliği gerçek
çalışma sayfasından hesaplanır; anlatım kendi panelinde kayar. Önizleme görseli
panelin boş yüksekliğine sığdırılır; pencere boyutu değişince tekrar hesaplanır.
İlerleme bölümü alta taşınır. Matematik anlatım alanında yalnız son Jarvis
cevabı gösterilir; konuşma geçmişi sunucuda korunur.

Matematikte tek dolar işaretleriyle gelen satır içi formüller de görüntülenir.
Anlatım talimatı, seçilen ara adımda gerçek sayıları yerine koyup hesabı göstermeyi
ister; tam sorunun cevabı Çöz isteğine bırakılır. Cebirsel pay anlatımında eş parça
çubuğu elenir; işlem adımları güvenli metin kutuları olarak çizilebilir. Bu
kontroller modelin bütün matematik cevaplarının doğru olduğunu garanti etmez.

Kaynaklar ve İlerleme üst çalışma sekmelerinde Programım’ın yanındadır. Kaynak
yönetimi ve sınav analizi Kaynaklar sekmesinde; hedef/özet İlerleme sekmesindedir.
Çalışma alanının altında tekrar eden açılır kaynak/ilerleme kutuları bulunmaz.
