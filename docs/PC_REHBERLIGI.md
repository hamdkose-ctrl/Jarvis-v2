# PC Yardımı

Windows masaüstü uygulamasında Ekran → PC Yardımı düğmesine basıp hedefini yaz.
Sesle “Bana bilgisayarda adım adım yardım et” diyebilir veya sohbetten
“PC yardımı: fotoğrafları telefona göndermek” yazabilirsin.

Jarvis'in ana penceresi yardım boyunca gizlenir. Ayrı bir Python/Tk sürecindeki
küçük panel tek talimat verir; bulunan hedefin kutusu tıklamaları engellemez.
Panel taşınabilir. Yaptım / Kontrol et yeni ekranı değerlendirir; Anlamadım aynı
amaç ve adımı daha basit açıklatır. Dur ve paneli kapatma hemen rehberliği
sonlandırır, ana pencere geri gösterilir. Konuşmadaki “dur” komutu da rehberliği
kapatır. Hiçbir uygulama açma/tıklama/yazma/silme/gönderme aracı modele verilmez;
işlemleri kişi yapar.

Ekran yalnız aktif yardım sırasında, kontrol gerektiğinde incelenir. Tıklama veya
Enter bırakıldıktan sonra kısa beklenir; en sık 10 saniyede bir, oturum başına en
fazla 20 otomatik kontrol kuyruğa alınır. Görüntü önceki kareyle aynıysa model
çağrılmaz. Sonrasında paneldeki Kontrol et veya sesli yaptım ile devam edilebilir.
Sürekli ekran yayını yoktur. Her kontrol ekranı geçici PNG olarak mevcut görüntü
sağlayıcısına yollar; yeni sağlayıcı/ücretli seçenek etkinleştirilmez. Gizlilik
modu ekranı yasaklıyorsa başlamaz ve devam eden yardım biter.

Panel/işaret ekran yakalanırken gizlenir. Yanıt hazırlanırken ekran anlamlı şekilde
değişmişse eski adım/hedef uygulanmaz. Kullanıcı değişimi, Dur, acil durdurma ve
kapanıştan sonra gelen yanıtlar gösterilmez. Telefondan rehberlik başlatılamaz.
Son amaç/adım profilde hatırlanır; yeniden açılışta ekran incelemesi kendiliğinden
başlamaz. “PC yardımı: devam” açık isteğiyle son amaç/adım yeni ekran üzerinden
yeniden değerlendirilir; eski hedef kutusu kullanılmaz. Ekran kareleri kalıcı kaydedilmez.

Hedef yalnız modelin görünür etiket, yüksek güven ve geçerli dar kutu vermesiyle
işaretlenir. Bunlar sezgisel kontrollerdir; hedef doğruluğunu bağımsız olarak
kanıtlamaz. İlerleme/tamamlanma değerlendirmesi de görüntü modeline dayanır.
Ana monitör desteklenir. Gerçek Windows paneli, yüksek DPI, mikrofon ve Gemini
ile uygulamalı deneme henüz yapılmadı; otomatik testler kontrol akışını doğrular.
