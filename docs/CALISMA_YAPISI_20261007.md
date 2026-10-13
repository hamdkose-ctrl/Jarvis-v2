> Güncel sürüm: Geliştirme Atölyesi kaldırılmıştır. Aşağıdaki eski sürüm incelemeleri tarihsel kayıttır.

# Çalışma ekranı: isimlendirme, bağımlılıklar ve anahtar koruması

## Yapılan değişiklikler

Çalışma ekranının bağlantı katmanı üç parçaya ayrıldı:

- `web_study_sources.py`: belge kaynakları, metin/konu cevapları, konu anlatımı ve sesli okuma.
- `web_study_exams.py`: ders seçimi, sınav analizi, test/deneme, yanlışlar ve çalışma planı.
- `web_study_media.py`: konu görselleri, videolar ve YouTube anahtarı ayarı.

`web_study.py` bu parçaları birleştirir ve eski endpoint adları için kısa uyumluluk yönlendirmeleri tutar. İş mantığı mevcut `study`, `studyexam` ve `studymedia` modüllerinde kalır.

Arayüz yeni, açıklayıcı adları kullanır:

| Eski ad | Yeni ad | İşlev |
| --- | --- | --- |
| study_ask | study_answer_text | Yalnız cevap metni |
| study_ask2 | study_answer_with_context | Belge seçimi, cevap ve konu bilgisi |
| study_remove | study_remove_document | Kullanıcının seçili çalışma belgesi ve üretilmiş indekslerini kaldırma |
| study_clear | study_clear_documents | Kullanıcının içe aktardığı çalışma belgelerini ve indekslerini temizleme |
| study_youtube_key | study_set_youtube_key | YouTube anahtarını ayarlama/silme |

Eski adlar önbellekteki arayüzler ve entegrasyonlar için çalışmaya devam eder. Silme işlemlerinin kapsamı değiştirilmedi; bu bakımda kullanıcı belgeleri silinmedi.

## Test edilebilirlik ve kullanıcı ayrımı

`StudyServices`, çalışma işlevlerinin ihtiyaç duyduğu bağımlılıkları açıkça sağlar. Tüm web çalışma ortamı işlevlere geçirilmez. Sınav ve medya bağımlılıkları da dışarıdan sağlanır; testlerde küçük taklit servisler kullanılabilir.

Kullanıcı profili bir açılış değerine sabitlenmez. Her işlem güncel istek bağlamından profilini alır. Paylaşılan tek köprüde eşzamanlı iki kullanıcı denemesi ayrı profillerle başarılı oldu.

## YouTube anahtarı

Anahtar `settings.json` içinde Windows DPAPI ile korunan `youtube_key_protected` alanında saklanır. Eski düz metin `youtube_key` kaydı ilk okumada korumalı kayda geçirilir; düz metin alan kaldırılır. Koruma başarısız olursa base64 veya düz metne geri düşülmez, mevcut ayarlar korunur.

Ayarlar geçici dosyaya yazılıp atomik olarak değiştirilir. Geçiş sırasında hata olursa eski dosya bozulmaz. API'nin ayar yanıtından hem düz metin hem korumalı anahtar alanları çıkarılır. YouTube durum yanıtları yalnız anahtarın varlığını bildirir; anahtar son karakterleri veya bağlantı hata URL'leri dönmez.

`YOUTUBE_API_KEY` ortam değişkeni tanımlanmışsa önceliklidir. Arayüzden silme yalnız kayıtlı anahtarı siler; ortam değişkenini kaldırmaz. YouTube anahtarı uygulama genelindedir; Windows hesabıyla korunur. Başka bir Windows hesabına taşındığında yeniden eklenmelidir.

İnternet erişimi gizlilik ayarıyla kapalıysa anahtar kaydetme işlemi YouTube'a deneme isteği göndermez. Anahtar değişiminde medya önbelleği temizlenir.

## Doğrulama

176 Python testi, iki modül entegrasyon kontrolü ve beş JavaScript test grubu geçti. Yeni testler gerçek Windows korumasını, eski kayıt geçişini, yazma/koruma hatasında ayarların korunmasını, yanıtların anahtar içermemesini, eski endpoint uyumluluğunu ve eşzamanlı profil seçimini doğruluyor.
