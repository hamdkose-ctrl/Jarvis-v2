# Geliştirme görseli önizlemeleri

Bu akış fotoğraf üretmez; geliştirme modülü SVG arayüz taslağı üretir.
SVG'nin yalnız XML olarak ayrıştırılabilmesi tarayıcıda görsel olarak
gösterilebildiği anlamına gelmez. SVG elemanları W3C SVG ad alanına
normalleştirilir; farklı ad alanları ve etkin/dış içerik reddedilir.
Ad alanı olmayan eski kayıtlar gösterilirken de normalleştirilir; kayıtlı
kaynaklar bu işlemle değiştirilmez. Bozuk kayıtlar kırık img yerine açıklama verir.

Modelin finish açıklamasına yazdığı görsel Markdown bağlantıları gösterilmez.
Yalnız visual/show_visual araçlarının gerçekten kaydettiği görseller sistemce
mesaja eklenir; aynı kayıt bir yanıtta iki kez eklenmez. Bu düzenleme modelin
uydurduğu veya hatalı kodladığı bağlantıların gerçek önizlemelerle karışmasını
önler. Önceden sohbete kaydedilmiş bozuk mesajlar geriye dönük yeniden yazılmaz.
Eski kayıtları yeniden görmek için "görselleri listele" ve ilgili görseli
gösterme isteği kullanılabilir.

Ekran görüntüsünde bir taslak görünürken diğer bağlantılar kırık görünüyordu.
Bağlantıların kaynakları paylaşılmadığından, o örneklerin kesin nedeninin
ad alanı eksikliği veya model bağlantısı olduğu doğrulanmış değildir.
