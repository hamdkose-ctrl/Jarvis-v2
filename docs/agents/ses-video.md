# Ses ve video (AGENTS.md alan notları)

Bu dosya AGENTS.md'den taşındı; bölümler olduğu gibi, sırası korunarak buradadır. Tarihli bölümler geçmiş kararı anlatır; bir bölüm başka bir bölümle çelişirse tarihi daha yeni ve "son karar" yazan geçerlidir. Kod değişince ilgili bölüm burada güncellenir.

## Ses tanıma süzgeci ve belirsiz komutlar — 14 Ekim 2026

- Türkçe dil kodu: Live oturumu `input_audio_transcription`'a `language_codes=['tr-TR']` ve özel sözlük verir (`live_session_config.transcription`). Eskiden bağlantı sonrası 8 sn içindeki "invalid/language" içeren her hata `live_stt_hint=False`'ı ayar dosyasına kalıcı yazıyordu (geçersiz anahtar bile); ayrıca 1011 sonrası sade mod dil kodunu düşürüyordu. Türkçe konuşmanın "Sí", "C'est bien" gibi yazıya dökülmesinin olası nedeni buydu. Artık reddedilen alan yalnız o çalıştırmada bırakılır (`stt_rejected`, `_stt_drop`: önce sözlük, sonra dil kodu; dar anahtar kelimeler), ayar dosyasına yazılmaz; sade modda da dil kodu gider. Eski `live_stt_hint` anahtarı okunmaz (Hamdi'nin PC'sinde `false` kalmış olabilir); elle kapatmak için `live_stt_language=false`.
- `modules/stt_guard.py` (model/ağ çağrısı yok, ayar `stt_guard`, varsayılan açık, arayüzde yok): sessizlik/gürültüde uydurulan kısa yabancı sözler (bilinen liste, Latin dışı yazı, Türkçe harfsiz kısa İspanyolca/Fransızca harfli söz) ve Jarvis'in son 20 sn içinde söylediğinin tekrarı (yankı) atılır. Rakam içeren söz (sayısal cevap, "12 + 7", "%50") hiçbir zaman yabancı sayılmaz. Yankı kelime düzeyinde ve birebir karşılaştırılır: Jarvis'in sözüyle kelimesi kelimesine aynı söz ya da ondan en az 4 kelimelik birebir parça; 3 kelimeden kısa söz yankı sayılmaz, harf benzerliği kullanılmaz ("Paylaşımı kapattım" sonrası "Paylaşımı kapat" komutu geçer). Live'da `flush_user` bunları sohbete/geçmişe yazmaz (yalnız uzunluk loglanır); Live modeli sesi kendisi dinlediği için asıl koruma Türkçe dil kodu ve istemdir. Live dışı yolda (`voice.recognize`: yerel, Gemini, Google) atılan söz "Anlayamadım" olur, ek Google/Gemini çağrısı yapılmaz. Jarvis'in sözleri `voice.speak` ve Live çıktı yazısından `note_said` ile kaydedilir. Mikrofon susturma/yankı kuyruğu (`live_microphone`) değişmedi.
- "Paylaşımı kapat/durdur/bitir", "paylaşmayı durdur" (ASCII yazım dahil) `engine_context._user_command` içinde mevcut `set_share(None)` yoluna gider; Live `komut` açıklaması ve istem bunu söyler. `set_share` gerçek sonucu söyler: açık paylaşım yoksa "yoktu", durdurma sonrası hâlâ açıksa "kapatamadım", hata "kapatılamadı". `share` olayı ve gizlilik denetim kaydı istenen durumdan değil, işlem sonrası `vision.mode()` değerinden üretilir: durdurma başarısızsa arayüze kapalı olayı gitmez ve "kapatıldı" kaydı yazılmaz; başlatma istenen moda ulaşmazsa denetim kaydı yazılmaz.
- Belirsiz istek: tek başına "kapat/aç/sil/gönder/başlat" (ve "kapatır mısın" gibi) modele gitmeden "Neyi … istiyorsun?" sorusunu döndürür ve canonical `pending_action` (`stage=clarify`, owner + 90 sn) olarak yazılır. Bu açık uçlu soru sonraki sözü tüketmez: cevabın `ANSWER_TO_PENDING` mi yeni istek mi olduğuna Understanding karar verir; yeni bağımsız bir capability Core planını bloke etmez. Sesle (`ses` kaynağı) tek başına duyulan "kapat" artık Jarvis'i kapatmaz, bu soruya gider; yazıyla "kapat"/"çık" eskisi gibi kapatır. Live istemi araç sonucu olmadan "kapatıyorum/açıyorum/yaptım" demeyi ve nesnesiz sözlerde tahmini yasaklar; `_CLAIM` "durduruyorum/sildim/yaptım" gibi sözleri de yakalar ve düzeltme notu belirsiz istekte araç yerine soru sordurur.
- Test: `tests/test_stt_guard.py`. Gerçek mikrofon, hoparlör yankısı ve canlı Gemini Live transkripsiyonu Hamdi'nin PC'sinde ayrıca denenmelidir.

## Bilgisayar sesi

- "Jarvis'i sustur" (`ACT.mute`, `speak` bayrağı) yalnız Jarvis'in konuşmasını keser.
- "Bilgisayarın tüm sesi" (`ACT.pcmute` → `pc_mute`, `pc_mute_state`) Windows ana ses çıkışını sessize alır.
- Sesli komutla ses kapatma/açma `engine_commands` içindedir ("sessize al", "sesi kapat", "sessizi kaldır").

## Video araçları kurulumu ve çalışma testi

Windows'ta isteğe bağlı `scripts/video_kurulum.bat`, kullanıcı Evet seçerse yalnız `winget install --id Gyan.FFmpeg --exact --source winget --scope user` çalıştırır. Uygulama kendiliğinden kurulum/indirme yapmaz. WinGet eksikse App Installer veya FFmpeg'in Windows dağıtımı gerekir. WinGet sonucu başarısızsa başarı denmez; kurulumdan sonra Jarvis yeniden başlatılır (PATH yenilenmesi). Paket kaynağı: https://github.com/microsoft/winget-pkgs/tree/master/manifests/g/Gyan/FFmpeg .

`video araçlarını kontrol et` / `video kurulum kontrol` yerel FFmpeg ve FFprobe sürüm çağrılarını, 0,3 saniyelik geçici H.264 kodlamayı ve gerçek dosya/codec/boyut/süre doğrulamasını yapar. Sürüm 5 sn, kodlama 15 sn, doğrulama 5 sn sınırındadır. Geçici çıktı temizlenir, ham araç çıktısı/dosya yolu gösterilmez; model/ağ/hesap/ses çağrısı yoktur. Eksik/bozuk/zaman aşımı başarı sayılmaz. Windows BAT/WinGet kurulumu gerçek PC'de ayrıca denenmelidir.

## Yerel anlatım çalışma kontrolü — 14 Ekim 2026

`yerel anlatımı kontrol et` mevcut kullanıcının kurulu Piper/Windows SAPI motoruyla sabit kısa metinden geçici WAV üretir. Dosya boyutu, PCM yapısı, süre, tam ses verisi ve 8/16 bit sessizlik kontrol edilir. Dosya temizlenir; hoparlörde oynatma, ses tercihi değiştirme, bulut/model indirme veya hesap isteği yoktur. Başarı dil/kalite testi değildir. SAPI dosya kapatmada hata verse bile COM temizliği yapılır ve çıktı başarı sayılmaz. Gerçek Windows/SAPI ve kullanıcının Piper modeli ayrıca denenmelidir.

