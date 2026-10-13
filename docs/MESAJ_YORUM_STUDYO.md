# Mesaj, yorum, Reels ve stüdyo akışları

Mevcut görev motoru genişletildi. Temel kurulum/yetkiler JARVIS_BIRLESIK_KULLANIM.md içindedir; bu dosya son eklenen kapsamı anlatır.

## Mesaj takibi

WhatsApp Business webhook verisi uygulama sırrıyla HMAC-SHA256 olarak doğrulanır. Yalnız yapılandırılmış phone_number_id kaydedilir. Mesaj ve teslim olayları tekil kimlikleriyle saklanır; aynı webhook yeniden gelirse aynı bildirim tekrarlanmaz. Okundu kaydı eski gönderildi/başarısız olayla geriye düşmez.

WhatsApp bağlantı dosyasına PC'de `webhook_enabled:true`, gerçek Meta `app_secret` ve uzun rastgele `verify_token` eklenir. Gönderim tokenı/telefon yapılandırması önceki rehberdedir. Jarvis yeniden açıldığında loopback 9898 alıcısı başlar. Meta callback yolu `/whatsapp/<kullanıcı-kimliği>` olur. İnternete erişen HTTPS ters vekil/tünel ve Meta webhook kaydı ayrıca kurulmalıdır; bu sürüm bunları otomatik açmaz. Ana ekran/GUI sunucusu herkese açılmaz. Gizli/yerel mod webhook alımını kapatır; daha önce alınmış inbox yerel olarak okunabilir.

`görev: WhatsApp gelen kutumdaki son mesajları incele` → account whatsapp/list_inbox. Bu kayıt yalnız bağlantı açıldıktan sonra alınmış olaylardır; geçmiş sohbetleri WhatsApp'tan geriye dönük çekmez. Medya eki indirilmez. Mesajların emirleri çalıştırılmaz; cevap ancak ayrı gönderim hedef yetkisi/tek içerik onayıyla mümkündür.

Telegram için bot dosyasında `consume_updates:true` seçilebilir. Varsayılan false eski sınırlı bakış davranışını korur. Açıldığında gözlenen update ID'leri/ilgili mesajlar önce diske yazılır, ancak bir sonraki çağrı bu kayıttan sonraki offset ile onaylar. Bot Jarvis'e ayrılmalıdır: başka istemcinin bot güncelleme kuyruğunu tüketebilir; yapılandırılmış sohbet dışındaki içerik kaydedilmez. Webhook kaldırılmaz/değiştirilmez.

## Yorum okuma ve cevap

- account youtube/list_comments + `resource_id` kesin video kimliği: OAuth kanalının videosu kontrol edilir, yorumlar düz metin olarak okunur.
- account instagram/list_comments + `resource_id` kesin medya kimliği: profesyonel hesap sahipliği kontrol edilir, yorumlar okunur.
- Sonuç ilk sınırlı sayfadır; daha fazla sonuç varsa belirtilir. Sonraki model adımı yalnız bu gerçek kayıttan analiz/cevap taslağı üretir.
- publish `operation:reply_comment`, `parent_id` kesin yorum, `destination` kendi kanal/hesap kimliği ve `text` ile cevap verir. Cevaplanacak yorumun ilgili hesaba ait içeriğin altında olduğu tekrar kontrol edilir.
- `hesap bağla youtube yorum` ayrı youtube.force-ssl OAuth tokenını alır.
- `hesap izin ver youtube_reply <kanal-kimliği>` veya `hesap izin ver instagram_reply <hesap-kimliği>` ayrı 24 saat hedef yetkisidir. Upload/yayın izni yorum yazma izni değildir; kaldırma aynı anahtarla yapılır.
- `text_from_task:<writer-adımı>` açık depends içindeki gerçek taslak dosyasını gönderim metnine dönüştürür. Özetle → cevap dosyası → publish zincirinde model ilk plan sırasında cevap metni uydurmak zorunda değildir. Nihai içerik outbox'a sabitlenir; onay ekranındaki metin uygulanır.

## Reels bekleme/kurtarma

Instagram publish girdisinde `media_type:REELS` ve erişilebilir HTTPS `video_url` gerekir. Container ID ilk hazırlamadan sonra saklanır. IN_PROGRESS yayını başarısız diye yeniden oluşturmaz; preparing olarak bekler. Engine 30 saniyeden sık olmadan aynı container'ın FINISHED durumunu denetler, aynı onay/yetkiyle yayınlar. `işlem takip <kimlik>` elle kontrol eder. Tek içerik onayı 24 saat geçerlidir; hedef grant'i iptal edilmiş/bitmişse otomatik devam etmez.

Bağlantı kesilip publication sonucu bilinmiyorsa unknown kalır; otomatik tekrar yoktur. Sending veya unknown durumuna düşmüş container yeni yayın isteğiyle tekrar çalıştırılmaz. Accepted yayın görevin kanıtına aktarılır; bu API kabulüdür, yayında sonsuza kadar kalma garantisi değildir. Video URL barındırma, Meta izinleri ve format kabulü gerçek hesapta ayrıca doğrulanmalıdır.

## Paralel uzman rolleri

`görev paralel: iki kaynaktan araştır, karşılaştır ve rapor hazırla` bağımsız research/okuma/üretim adımlarını en çok 3 worker ile çalıştırır. Writer/verify gerçek bağımlıları bitmeden başlamaz. Kullanıcı ve istek ContextVar'ları her worker'a ayrı taşınır. Kod, tarayıcı ve dış yayın bu modda reddedilir; kaynak/dosya/hedef çakışması yaratabilecek dış etkiler paralel uygulanmaz. Varsayılan görev akışı sıralıdır. Yeni framework kurulmadı.

## Yerel üretim stüdyosu

Örnek:
```json
{"scenes":[{"caption":"Giriş","duration":5},{"caption":"İkinci sahne","duration":5}],"layout":"portrait"}
```

Bunu `video üret <JSON>` komutunda kullanabilirsin. 1–12 sahne, en çok 300 saniye; portrait 720×1280, landscape 1280×720, square 1080×1080. Her sahneye Jarvis dosya alanındaki `image` eklenebilir; prepare gerçek SHA-256'yı çıkarır. Görselsiz sahne yerel yazı kartıdır. Caption literal metindir; FFmpeg komutu veya HTML değildir. Çok sahneli montaj ve isteğe bağlı `audio` yerel kaynaklardan üretilir.

`narration` (en çok 1800 karakter) seçilirse kurulu Piper modeli veya Windows SAPI dosyaya ses üretir. `connector_users/<kullanıcı>/media_voice.json` içinde `backend:auto|piper|sapi`, Piper için `model:<yerel.onnx>` verilebilir. Model indirilmez, ücretli/bulut TTS'e geçilmez. Anlatım yok/uygun değilse unavailable olur; sessiz tamamlandı sayılmaz. Ses daha uzunsa sahneler oranlı uzatılır; toplam 300 saniyeyi geçerse işlem durur. Bu kaba sahne zamanlamasıdır; kelime bazlı dudak eşleme değildir.

Bu stüdyo kaynak görsel/metni düzenleyen yerel üretim yoludur; foto-gerçekçi generatif model içermez. Gerçek FFmpeg/FFprobe montaj/codec/süre/boyut/ses doğrulaması yapıldı. Piper ve Windows SAPI cihaz/voice kalitesi canlı PC'de denenmelidir.

## Doğrulama ve kaynaklar

İmzalı/bozuk webhook, HTTP challenge/signature, kayıt deduplikasyonu, teslim sırası, sahibine bildirim, bot cursor, yorum sahipliği, reply izin ayrımı, aynı Reels container'ı, paralel rol bağlamı/bağımlılığı, gerçek caption/montaj/ses videoları ve dosyadan gönderim metni test edildi. Dış servis/model sonuçları fixture'larla sınanır; hesap/OAuth, yayın kalitesi, gerçek Windows mikrofon/TTS/pencere ve HTTPS callback kabulü ayrıca gerekir.

Resmi API/CLI başvuruları: https://developers.google.com/youtube/v3/docs/commentThreads/list ; https://developers.google.com/youtube/v3/docs/comments/insert ; https://www.postman.com/meta/instagram ; https://www.postman.com/meta/whatsapp-business-platform ; https://github.com/rhasspy/piper ; https://github.com/OHF-Voice/piper1-gpl ; https://learn.microsoft.com/en-us/previous-versions/windows/desktop/ms720892(v=vs.85) .

## Yerel servis kurulum kontrolü — son sürüm

`hesap durumu`, `hesap kurulumu kontrol` ve `servis durumu` mevcut kullanıcı için OAuth dosyaları, servis yapılandırmasının gerekli alanları, WhatsApp webhook/maliyet yetkisi, Telegram güncelleme tüketimi ve FFmpeg/FFprobe/Piper/SAPI önkoşullarını gösterir. Kontrol ağ çağrısı, OAuth yenileme, giriş penceresi veya ayar yazımı yapmaz; sır ve dosya yolu göstermez. Dosyanın/programın bulunması canlı bağlantı, geçerli izin veya çalışma testi değildir. Kullanıcı ve istek sahibi eşleşmelidir. Gerçek Windows/mikrofon/hesap, HTTPS webhook ve ses kalitesi kabul testleri hâlâ açıktır.
