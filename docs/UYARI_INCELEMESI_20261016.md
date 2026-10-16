# Uyarı incelemesi ve ortak PC kabulü — 16 Ekim 2026

İnceleme tabanı: Jarvis-v2 main `0ac1c5a4` (PR #44). Haber teslimi ve kısa devam komutu düzeltmeleri korundu. Drive taslakları koda aktarılmadı; kullanıcı tarafından paylaşılan uyarı metni güncel kod ve bu sohbetteki PC sonuçlarıyla karşılaştırıldı.

| Uyarı | Karar ve kapsam |
|---|---|
| Dört sekmeli yeni HUD mevcut arayüzü ezebilir | Uygulanmadı. Onaylı hologram, 18 düğümlü menü, dock ve mevcut SSE korunur. Son onaylı Selçuklu arka planı da korunur. Harici taslak bir uygulama talimatı değildir. |
| Her özellik ağır bağımlılıkları açılışta yükler | Genelleme doğrulanmadı. PDFium, Office, Whisper ve kamera bağımlılıkları kullanım noktasında yükleniyor. Çalışma/medya/OCR içe aktarmasının ağır okuyucuları yüklemediği ayrı süreçte sınanır. Büyük eklenti dönüşümü veya kilit dosyası değişikliği yapılmadı; gerçek PC RAM/gecikme ölçümü açık. |
| FFmpeg eksik | Eski rapor mevcut ortamın kanıtı değildir. Kullanıcı daha sonra gerçek video üretimini bildirdi. Yeni `--video` mevcut gerçek H.264/FFprobe testini kabul raporuna ekler; kurulum veya indirme yapmaz. |
| Instagram yalnız görsel destekliyor | Kodda Reels ve yorum yanıtlama yolları mevcut; gerçek hesap kabulü ayrı. WhatsApp geçmişi API'den çekilmez, webhook kayıtları yerelde saklanır. Telegram bot erişimi kişisel hesabın tamamı değildir. Yeni hesap veya ücret yetkisi açılmadı. |
| Mock test Windows kabulü sayılıyor | Otomatik sonuç ve kullanıcı beyanı ayrıldı. Ses, kamera veya yeniden başlatma için kod testi otomatik passed üretemez. |
| Taranmış PDF okunamıyor | Açık yerel OCR komutu eklendi. Varsayılan Gmail/PDF okuyucusu değişmedi. Türkçe Tesseract dil dosyaları kullanıcı PC'sinde ayrıca gerekli. |
| Genel masaüstü ve ses gürültüsü | Hesap Makinesi kabulü bütün uygulamaların doğrulandığı anlamına gelmez. Kullanıcının başarılı ses denemeleri geçmiş kabul olarak korunur; farklı PC, gürültü ve ilgili kod değişikliği tekrar kabul gerektirir. Ses motoru veya izin kapıları değiştirilmedi. |

## Yerel OCR kullanımı

Sohbette izinli klasördeki tek bir PDF'nin tam yoluyla:

```text
"C:\Users\Hamdi\Documents\tarama.pdf" yerel OCR ile oku
```

Mevcut dosya erişim denetimi uygulanır. OCR metni ekranda gösterilir, `çıktı al` için mevcut son belge bağlamına alınır. Otomatik bulut/model çağrısı, indeksleme, indirme veya kalıcı PDF/görüntü kopyası yoktur. Mevcut Gmail ek okuması OCR'a kendiliğinden geçmez; PDF'yi kullanıcı dosya alanına kaydedip açık komut vermek gerekir.

Tesseract PATH içinde, `tur` ve `eng` dil dosyaları kurulu olmalı. `tesseract --list-langs` ile kontrol edilir. Eksikse işlem açıklamayla durur; sessizce İngilizceye veya buluta geçmez. Python tarafı mevcut pypdfium2 ve Pillow'u kullanır; kilit dosyası değiştirilmez.

Sınırlar: 4 MiB, ilk 10 sayfa, 20.000 karakter, dış okuyucuda 30 saniye, sayfada en uzun kenar 2200 piksel. Tesseract sayfa çağrısı en çok 6 saniyedir. Süre sınırı dolarsa başarı üretilmez; son yerel OCR alt işlemi en çok kendi kalan sayfa süresince kapanmayı tamamlayabilir. Sayfa/metin sınırında kesilme belirtilir. OCR harf ve sayı doğruluğu garantisi değildir. Şifre çözülmez, Office makrosu çalıştırılmaz.

## Tek Windows kabul listesi

1. Jarvis'i güncel kodla yeniden başlat; mevcut ana ekran, menü ve paylaşım aç/kapat davranışını kontrol et.
2. `scripts\v2_kontrol.bat --gmail --desktop --narration --video --skip-suite` çalıştır. Bu komut Gmail okur, Hesap Makinesi görevi yapar ve yerel geçici ses/video üretir; mail/video göndermez veya yayımlamaz. Video testi gerçek codec, boyut ve beklenen kısa süreyi doğrular.
3. Türkçe taranmış bir PDF'yi yukarıdaki OCR komutuyla oku. Türkçe harfleri ve sayıları belgeyle karşılaştır; eksik dil paketi durumunda anlaşılır ret beklenir.
4. Mevcut kayıtlı hedefi sürdür: erişilemeyen kaynaktan başka kaynağa geçiş, gerçek tarihli haber, rapor dosyası ve doğrulama kontrol edilir. Kısmi rapor bütün hedefin tamamlandığı anlamına gelmez.
5. Yalnız gerçekten denenen donanım akışlarını kullanıcı beyanı olarak kaydet. Örnek:

```powershell
.\scripts\v2_kontrol.bat --skip-suite --confirm-manual wake_word_microphone speaker_voice_quality
```

`reported_passed` kullanıcı beyanıdır, otomatik `passed` değildir. Beyan kullanıcı ve bilgisayar kimliğiyle ayrılır; Windows'ta işletim sistemi MachineGuid değeri, Linux'ta machine-id, bulunamazsa MAC bilgisi kullanılır. Ham kimlik rapora/kayda yazılmaz. Aynı işletim sistemi kimliğiyle klonlanmış bilgisayarlar ayrıca yeniden kabul gerektirir. Tarihi sonraki raporlarda görünür. İlgili kod, ayar veya cihaz değişirse tekrar denenmelidir. Örneğin önceki ses beyanını kaldırmak için `--reset-manual speaker_voice_quality` kullanılır. Genel hesap kabulünü yalnız gerçekten test edilen kapsam için yorumlayın; düğme/anahtar varlığı canlı servis başarısı değildir.

Canlı hesap izinleri, gerçek Windows donanımı ve Türkçe OCR kalitesi geliştirme ortamında tamamlanmış sayılmaz. Yeni sosyal hesap açma, otomatik yayın, genel fareyle sınırsız uygulama kontrolü veya ücretli model geçişi eklenmedi.

## Doğrulama sonucu

Güncel main #44 ile 1331 Python testi (1 Windows DPAPI atlaması), 25 Node ve 6 smoke grubu başarılı. 14 odaklı kontrol geçti. Seçilebilir metni olmayan üretilmiş PDF, gerçek Tesseract İngilizce motoruyla okundu; Türkçe dil dosyası eksikliği sessiz İngilizce geri düşüşü yapmadan reddedildi. Gerçek FFmpeg/libx264 üretimi ve FFprobe boyut/süre doğrulaması geçti. Son salt okunur kural denetimi geçti. Bu sonuçlar Windows Türkçe OCR, mikrofon/kamera veya canlı hesap başarısı olarak sunulmaz.
