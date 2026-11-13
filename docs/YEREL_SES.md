# Yerel ses — ilk deneme

Bu sürüm faster-whisper ile Türkçe sesi PC'de yazıya çevirir. İlk aşamada yalnız masaüstündeki **Konuş** düğmesi kullanılır. Varsayılan Gemini/Google davranışı korunur; özellik kapalı gelir. Piper dahil değildir.

## Kurulum

Jarvis kapalıyken kökteki `kurulum.bat` çalıştır. faster-whisper, small modeli, belge eklentileri ve tarayıcı bu tek kurulumda hazırlanır. Ayrı pip komutu gerekmez; kurulum internetten dosya indirir.

Kilit dosyasına tahmini sürüm eklenmedi. Çalışan PC ortamında kurulum ve gerçek deneme başarılı olduktan sonra Ayarlar'dan bağımlılık sürümlerini sabitle. Python 3.14 için uyumlu paket bulunamazsa kurulum eski ortamı korur; hatayı kurulum.log üzerinden bildir.

1. Ayarlar › Ses bölümünde `small` modelini seç. Yavaş kalırsa `base` denenebilir.
2. Kurulum small modelini hazırladıysa bu adımı atla. Model eksikse veya base seçtiysen Normal modda **Modeli indir** düğmesini kullan. Bu açık işlem Hugging Face'ten yalnız model dosyalarını indirir. Ses kaydı gönderilmez. Paket kurulumu/model indirmesi Jarvis açılışında ya da ilk konuşmada yapılmaz; açık kurulum veya Modeli indir işlemi gerekir.
3. **Durumu yenile** ile modelin hazır olduğunu kontrol et.
4. Ses tanımada **Yerel · yalnız Konuş düğmesi** seç, Kaydet ve Jarvis'i yeniden başlat.
5. Konuş düğmesini kullan. İlk model yüklemesi sonraki komutlardan daha yavaş olabilir.

Yerel denemede Hey Jarvis dinlemesi açılmaz; mikrofon yalnız düğmede dinlenir. Seçim **ses tanıma motorunu** değiştirir (bulut `voice.recognize` ↔ yerel Whisper): Gemini Live hat olarak 11 Kasım 2026'da emekli edildi (`tests/test_live_retirement.py`), yani "canlı oturuma dönme" diye bir yol yoktur ve hiçbiri açılmaz. Yerelden buluta dönmek için Gemini/Google seç, Kaydet ve yeniden başlat. Ses tanıma tercihi bilgisayar ayarıdır; yalnız PC kullanıcısının mevcut komut motoruna gönderilir, Android değiştirilmedi.

## Gizlilik ve sınırlar

- Yerel tanıma, model eksik ya da bozuk olsa da Gemini/Google'a geçmez. Model yüklemesi `local_files_only=True` ve yerel tokenizer ile çalışır.
- Gizli/Yerel modda model indirme başlatılmaz. Önce Normal modda indirip sonra bu modlara geçebilirsin.
- Yerel STT yalnız sesi yazıya çevirir. Normal/Gizli modda komut metni mevcut model ve gizlilik kurallarına göre işlenir. Tam çevrimdışı cevap için Yerel mod ve hazır Ollama gerekir.
- Sesi okuma ayrı iştir. Yerel mod Windows sesini kullanır; normal modda mevcut ses sağlayıcısı kullanılır.
- Model dosyaları `.jarvis/models/stt/` altında saklanır; kaynak depoya girmez. Tek CPU int8 modeli bellekte tutulur. Gerçek RAM ve gecikme PC'de ölçülmelidir.
- Ham kayıt ve tanınan metin yeni STT günlüğüne yazılmaz; yalnız model adı/süre kaydedilir (süzülen segment sayısı da yazılır, metni yazılmaz). Normal sohbet geçmişi mevcut kurallarla sürer.
- Uydurma cümle süzgeci: Whisper sessizlik ve gürültüde "Altyazı M.K.", "İzlediğiniz için teşekkürler" gibi cümleler uydurabilir. Bilinen kalıplar ve düşük güvenli segmentler (`no_speech_prob` > 0,6 ve `avg_logprob` < -1,0; `compression_ratio` > 2,4) atılır. Hepsi atılırsa komut gitmez ve "Anlayamadım, tekrar söyler misin?" denir. "Altyazı ekle" gibi gerçek komutlar süzülmez; kalıplar tam eşleşmede (ve "altyazı m.k." ile "izlediğiniz için teşekkür" başlangıçlarında) atılır.
- Kayıt bitince arayüz yazıya çevrilirken "düşünüyor" durumuna geçer; "Dinliyorum"da kalmaz.
- Özel kelimeler: Ayarlar › Özel kelimeler (virgülle) yerel tanımada da Whisper'a kısa bir ipucu olarak verilir (en çok ~200 karakter, tam kelimelerle). Whisper ipucunu çıktıya geri yazarsa (tamamı ya da 3+ kelimelik parçası) o sonuç atılır; tek başına söylenen bir özel kelime atılmaz.
- Hız / doğruluk: Ayarlar › Ses › Yerel ses hızı (`local_stt_beam`): En doğru (5, varsayılan), Dengeli (2), En hızlı (1). İşlemcide yavaşsa düşür; hemen geçerli olur. Kısa komutlarda doğruluk düşebilir, PC'nde dene.
- Açılış hazırlığı: yerel ses açıksa ve model zaten inmişse Jarvis açılırken modeli arka planda yükler, ilk Konuş basışı beklemez. İndirme ve ağ kullanmaz; hata olursa ilk basışta yüklenir. Model RAM'de kalır (small için yaklaşık 0,5-1 GB, PC'de ölçülmeli).

## Doğrulama

`run_tests.bat` çalıştır. Ardından PC'de Türkçe dosya/kişi adları, sessizlik, TV/YouTube/yankı, mikrofonu kapatma ve internetsiz kullanım denenmeli. Gizli/Yerel modda model eksikken de buluta istek gitmediğini kontrol et. Bu donanım denemeleri taklit testlerinin yerine geçmez.
