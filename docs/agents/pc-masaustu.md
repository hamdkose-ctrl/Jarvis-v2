# PC ve masaüstü kontrolü (AGENTS.md alan notları)

Bu dosya AGENTS.md'den taşındı; bölümler olduğu gibi, sırası korunarak buradadır. Tarihli bölümler geçmiş kararı anlatır; bir bölüm başka bir bölümle çelişirse tarihi daha yeni ve "son karar" yazan geçerlidir. Kod değişince ilgili bölüm burada güncellenir.

## Altyapı tamamlama ve kabul paketi — 14 Ekim 2026

- `pc_contracts` mevcut 11 mutasyon girişine tür ve istek sahibi denetimi, son 200 işlem için argümansız kullanıcı kaydı ve ortak sonuç sınıfı ekler. `system_control` girişleri aynı sınırdan geçer; `pc_steps` çift kayıt üretmez. Pencere/odak/izin korumaları aynı kalır. Kayıt başta saklanamazsa fiziksel işlem başlamaz; son kayıt saklanamazsa işlem kendiliğinden tekrarlanmaz. Kapatmada yalnız komut iletimi kanıtlanır; gerçek kapanış veya klavye işleminin uygulamadaki sonucu garanti edilmez.
- `Profile.edit_fact` kesin eski metin ve indeksle, profil kilidi içinde düzeltme/silme yapar; disk hatasında belleği geri alır. `fact_update` ortak araca bağlıdır. Modelsiz `hafızamı göster`, `hafıza düzelt: eski | yeni`, `hafıza unut: tam kayıt` yalnız onaylı facts alanını etkiler. Diğer veri alanlarını topluca silmez.
- `task_workflows` rapor, mail taslağı, kod taslağı ve yerel video için mevcut worker'larla sabit üretici/doğrulayıcı zincirleri kurar. Planlayıcı çağrısı yoktur; üretici çağrıları ve mevcut geliştirme/hesap izinleri korunur. Dış gönderim veya ücretli üretim eklenmez.
- `acceptance_checks` ve `scripts/v2_kontrol.bat` kaynak/sürüm testi ve yerel önkoşul raporu üretir. Gmail, Hesap Makinesi ve WAV denemeleri ancak ilgili CLI bayrağıyla çalışır; varsayılan gerçek hesap/donanım çağrısı yoktur. Yeni masaüstü görevine UUID eklenir; kabul yalnız bu çağrının yeni kimlikli kaydını kullanır, eski done kaydı başarı sayılmaz. Gönderim, mikrofon kaydı ve kamera açılmaz. Elle yapılacak kabul pending kalır; rapor Gmail içerik/kimlik veya anahtar saklamaz ve Git kapsamı dışındadır. Ayrıntı: `docs/V2_TAMAMLAMA_VE_PC_KABUL.md`.
## Gerçek PC kabul geri bildirimi — 14 Ekim 2026

Ekran paylaşım komutu ASCII ş/i yazımını da mevcut `set_share` yolunda tanır; uygulama açmaya düşmez. İlk mailin ek komutları yalnız bir mail seçer ve sonuçlarını sade gösterir; hash/adım günlükleri kayıt ve açık görev durumunda korunur. Boş ek, okunacak ek yok şeklinde anlatılır. Kuyruk durumu işin adını, bekleme süresini ve açık iptal/sonuç komutlarını gösterir; bildirimi de sonuç özeti taşır. Masaüstü görevleri her mevcut kaydetme noktasında çalışma turu süresini ölçer; yeni UIA çağrısı/model çağrısı yoktur. Normal sonuçta ham kontrol kanıtı gizlenir; `PC görevi ayrıntıları` ile istenir.

