# Arayüz güncellemesi — 13 Ekim 2026

## Yapılanlar
- Sıcak ufuklu yerel arka plan, gerçek hareketli silüet, biraz daha güçlü göğüs/omuz nefesi, mavi göğüs noktaları. Dağların ardından gökyüzü açılır. Mavi/turkuaz/sarı ve lav seçenekleri korunur.
- Ana ekranda sistem bilgisi katlanır, Sohbet/Çalışma/Menü erişimi ve yazma/konuşma çubuğu vardır.
- Sohbet ve dosyalar tek alanda. Dosya arşivi açılır paneldir; dosya eklenince türüne göre seçenek gelir. Seçenek yalnız talimatı doldurur; gönderme kullanıcıdadır. Dosya açma, klasör, telefon ve diğer mevcut işlemler korunur.
- Çalışma alanı geniş kaynak yüzeyi, seçime yakın anlatım, katlanabilir çalışmalar/çalışma türleri, kaynaklar, gerçek notlar ve geçmiş erişimi. Küçük ekranda anlatım kaynak altında açılır.

## Doğrulananlar
- 20 mevcut Node test grubunun tamamı ve webui JavaScript sözdizimi geçti.
- Gerçek Chromium'da 1440×900 ve 390×844 boyutları denendi. API cevapları test verisiyle taklit edildi; canlı modele istek gönderilmedi.
- Dosya arşivi, dosyayı sohbete ekleme, üç bağlamsal işlem, Escape ile kapatma, çalışma alanı, notların gösterilmesi ve dar ekran kontrol edildi; tarayıcı JavaScript hatası yok.
- Hologram testleri mevcut ses/durum köprüsü, tıklama sınırı, palet, sakin mod, yeniden oynatma ve kaynak temizliğini geçti.

## Doğrulanmayanlar
- Canlı Windows mikrofon/TTS, gerçek kaynak PDF'leri, gerçek yükleme/gönderme, model cevapları ve gerçek GPU akıcılığı.
- Taslak görsel matematik metni ve grafikleri örnektir; uygulama gerçek kaynak ve gerçek cevapları gösterir, örnek metin gömülmedi.
- Python motoru değişmedi; tam Python testleri bu arayüz işi için tekrarlanmadı.

GitHub'a gönderim, commit veya PR yapılmadı. Android, motor, API ve ses işleme dosyaları değişmedi.
