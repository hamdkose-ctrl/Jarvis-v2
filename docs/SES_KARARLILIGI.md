# Ses kararlılığı düzeltmeleri

Ses değişiminde yeni Live oturumu eski resumption handle olmadan açılır.
Aynı ses seçiliyse ayar yazılmaz ve yeniden bağlantı yapılmaz. Yeni oturumun
talimatı güncel sesi ve ayarlardan okunan asistan adını içerir. İsim söylemenin
ayar olarak kaydedilmesi mevcut komut yönlendirmesine bağlıdır.

Ses değişimi istendiğinde eski oturumun sonraki ses ve yanıt transkripti
bastırılır. Önceden kuyruğa alınmış kısa geçiş sözü bittikten ve araç
tamamlandıktan sonra yeni oturum açılır. Değişiklik onayı yalnız yeni
bağlantı kurulduktan sonra seslendirme kuyruğuna eklenir. Bağlantı kurulamazsa
başarı onayı söylenmez. Cümleyi Gemini Live üretir; donanımda doğrulama gerekir.

İlk transkript bekleme süresi bağlantı açıldıktan sonra başlar. Kazanç öncesi
sesin ortam tabanına göre en az üç kare yükselmesi yerel etkinlik kanıtıdır;
bu bir konuşma tanıyıcı veya kullanıcı doğrulaması değildir. Bu kanıt süreyi
uzatır, ancak transkript yoksa oturum en fazla max(60, 4 * bekleme) saniye
bekler. Tanı mesajı transkript yokluğunu sessizlikten ayırır. Gerçek mikrofon,
Türkçe anlama doğruluğu ve hoparlör yankısı Windows üzerinde doğrulanmalıdır.
Jarvis konuşurken mevcut hoparlör susturma davranışı korunur; tam çift yönlü
ses ve akustik yankı giderimi bu değişikliğin kapsamında değildir.

## İsteğe bağlı yerel tanı

Kullanıcının mevcut settings.json dosyasında `live_audio_diagnostics: true`
ayarı etkinleştirilirse sonraki Live konuşmasında iki kayıt alınır:

- `tani_mikrofon.wav`: filtre ve kazanç öncesi, mikrofonun kendi örnek hızında.
- `tani_gonderilen.wav`: send_realtime_input başarılı döndükten sonra kaydedilen
  16 kHz ses. Bu, sunucunun sesi anladığını veya işlediğini kanıtlamaz.

İki dosya oturum biterken DATA_DIR altında aynı son 30 saniyelik zaman
penceresiyle yazılır. Gönderilmeyen zaman aralıkları sıfırdır; duraklamalar
birleştirilmez. Dosyalar her oturumda üzerine yazılır, ağ üzerinden ayrıca
paylaşılmaz. Mikrofon kaydı Jarvis konuşurken ortam sesini de içerebilir.
Varsayılan kapalıdır. Kapatmak için ayarı false yapın; önceki kayıtların
silinmesi kullanıcının tercihidir. Son oturumun son_ses.wav kaydı artık varsayılan kapalıdır; yalnız live_save_audio=true ile etkinleştirilir. Mevcut eski kayıtlar otomatik silinmez.

FatihMakes/Mark-LV incelemesi, ses değişimi ile sıradan yeniden bağlantının
ayrılması fikrine kaynak oldu. Bu değişiklikte o depodan kod kopyalanmadı.

## İlk yanıt gecikmesi ve bitişik komut

Uyanma sonrasında ilk 160 ms artık atılmaz. Tetikleyen son 80 ms de korunur;
uyanma kelimesinin tüm kaydı varsayılan olarak gönderilmez. Bu değişiklik
"Hey Jarvis, merhaba" gibi bitişik komutların başlangıcını korumayı amaçlar;
uyandırma kelimesinin son hecesi de modele ulaşabilir. Gerçek doğruluk ve
yanlış uyanma oranı cihazda doğrulanmalıdır.

Logdaki `Ses zamanlaması` satırları uyanmadan itibaren ilk bağlantı, ilk
başarılı ses gönderimi, ilk kullanıcı transkripti, ilk model ses paketi ve
ilk yanıtın output stream'e yazılması sürelerini gösterir. Uyanma bip'i yanıt
sayılmaz. `output_write` donanımdan duyulma onayı değildir; sürücü gecikmesi
buna eklenebilir. 0,6–0,8 saniyelik oynatma tamponu değiştirilmemiştir.
