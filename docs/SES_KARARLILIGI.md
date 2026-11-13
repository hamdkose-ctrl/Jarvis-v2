# Ses kararlılığı düzeltmeleri

> **Geçmiş bölüm (11 Kasım 2026):** aşağıdaki ilk üç başlık Gemini Live oturumunun
> davranışlarını anlatır. O hat emekli edildi (`modules/live.py` ve `live_*` yığını,
> `voice_timing` köprüsü ve `audio_diagnostics` silindi), bu yüzden burada anlatılan
> hiçbir davranış artık üretimde değildir ve adları geçen ayar anahtarları hiçbir yerden
> okunmaz. Metin, kararların gerekçesini okunur tutmak için duruyor. Emekliliğin kanıtı:
> `tests/test_live_retirement.py` ve `docs/agents/ses-video.md`.

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

> 11 Kasım 2026: bu opt-in emeklilikle birlikte fiziksel olarak kaldırıldı (`_save_sent` /
> `son_ses.wav` / `live_save_audio` üretimde yok). Yani ham mikrofon sesi artık hiçbir yolda
> diske yazılmaz; kapalı bir varsayılan değil, yok olan bir yüzeydir. Kullanıcının kendi
> verisi olan eski dosyalar bu PR'da silinmez. Kanıt: `tests/test_live_retirement.py::CallerZeroResidueTests`.

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

## Ses susturma ve görev iptalinin ayrılması — 10 Kasım 2026

Kullanıcının `sus`, `yeter`, `sesini kes` ve `konuşmayı kes` komutları yalnız oynatılan sesi durdurur. İlgili kullanıcının aktif Core/Brain isteği ve arka plan görevi `requests_state.cancel` ile iptal edilmez; sesli uyarı bekleyen bir işin kendisi değildir. Önceki doğrudan `dur` ve `stop` komutlarının aktif isteği iptal etme davranışı korunur. Bu ayırım komut yönlendirme aşamasına aittir; 11 Kasım 2026'da üretim ses hattına bağlandı (aşağıdaki "Üretim hattına bağlanması" bölümü).

Birim testi ses durdurma çağrısının yapıldığını ve görev iptali/PC guide stop çağrılarının yapılmadığını doğrular; gerçek Windows ses ve görev paralelliği ayrıca kabul edilmelidir.

## Üretim hattına bağlanması — 11 Kasım 2026

Yukarıdaki ayırım artık yalnız yönlendirme aşamasında değildir: `sus/yeter/sesini kes/konuşmayı kes`
tek birleşme noktasında (`engine_queue.submit`) kooperatif ses kesimi (`voice_runtime.interrupt_active`)
ve o turun yanıtına sessize alma (`requests_state.mute_speech`) üretir; enqueue olmamış yanıt
`VoiceLane._privacy_gate`te `VOICE_SUSPENDED_TURN` ile reddedilir, yani model sonradan bitirse bile
konuşma yeniden başlamaz. GoalState/worker iptal edilmez, yazılı sonuç korunur. `dur/stop` görev
semantiği sessize dönüştürülmez. Kanıt: `tests/test_voice_runtime_bridge.py::test_sus_mutes_the_stopped_turns_speech_not_the_running_request`,
`test_sus_stops_the_remaining_chunks_of_an_utterance_already_playing`, `test_web_or_voice_stop_reaches_same_active_lane_without_core_cancel`.
**Bu maddedeki sessize alma kapsamı 12 Kasım 2026'da daraltıldı; aşağıdaki bölüm güncel otoritedir.**

## Sus'un susturma kapsamı — 12 Kasım 2026

`sus` yalnız **mevcut konuşmayı ve ona ait gecikmiş ses çıktısını** susturur. `interrupt_active()`,
`VoiceLane.interrupt()`ın döndürdüğü kimlikleri tek kaynak alır: kesilen anda oynatıcıda veya ses
kuyruğunda olan konuşmaların `turn_id`leri ve bu sahibin hoparlörüne en son gerçekten inmiş (`playback_started`)
tur. `requests_state.mute_speech(slug, turn_id)` bu kimliklere çağrılır; kullanıcının ses sahibine hiç
verilmemiş açık işleri susturulmaz, dolayısıyla iki bağımsız işten biri konuşurken "sus" demek diğerinin
ilerideki sesli bildirimini kaybetmez. Eski konuşmanın gecikmiş cevabı yeniden başlamaz (`VOICE_SUSPENDED_TURN`),
Core görevleri ve yazılı sonuçlar etkilenmez, yeni bir genel iptal veya ikinci ses yöneticisi eklenmedi;
"dur/stop" görev kapsamı (`requests_state.cancel(owner)`) ayrı ve değişmedi. Kanıt:
`tests/test_voice_runtime_bridge.py::test_sus_keeps_the_other_jobs_later_spoken_result_while_muting_its_own`,
`test_sus_never_mutes_a_request_the_lane_was_never_given`. Eski (kapsamı geniş) davranışa karşı bu iki test
fail verir; `test_sus_mutes_the_stopped_turns_speech_not_the_running_request` iki durumda da geçerlidir.
