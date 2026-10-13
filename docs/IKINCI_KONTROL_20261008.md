# İkinci Kontrol — 08.10.2026

Bu paket önceki genel kontrol paketindeki kaynakları ve bu turdaki düzeltmeleri birlikte içerir. GitHub’a yüklenmemiştir.

## Düzeltilenler
- Çok adımlı komutlar yeni `pending_action` onayını ve diğer eksik bilgi sorularını beklemiyordu. Bütün oturum bekleme alanları ortak `awaiting_input` denetimiyle kontrol edilir; bir adım onay/yanıt beklerse sonraki adım çalışmaz.
- Komut zincirinde kullanıcı değişirse kalan adımlar yeni kullanıcının adına kendiliğinden yürütülmez. Zincir durur, açıklama gösterilir. İlk oturumun çok adımlı işlem işareti her durumda temizlenir.
- İç içe telefon/kullanıcı bağlamlarında `_home` geçici kullanıcıyla ezilebiliyordu. Gerçek PC kullanıcısı korunur; iç bağlamdaki hata sonrası profil, oturum ve model kullanıcısı geri gelir.
- Gecikmeli devir/öğrenme/sabah bildirimleri kapatma olayını dikkate alır. Devir bildirimi PC sahibine yazılır, ses kuyruğunda sahibinin kimliği taşınır. Öğrenme raporu PC kullanıcısının model bağlamıyla hazırlanır; PC kullanıcısı değişirse eski kullanıcının bildirimi gösterilmez.
- Sabah özeti artık geçici telefon profilini kullanmaz. Yakalanan PC profili ve ona bağlı veri toplama işleviyle hazırlanır; ağ çağrıları sırasında ana komut kilidi tutulmaz. Kullanıcı değişimi/kapatma/uyku durumunda sonuç gösterilmez ve görülmüş olarak işaretlenmez.
- Arka plan bildiriminde UI geri çağrısı hata verirse geçmiş kaydı korunur, hata kaydedilir; bu istisna bildirim döngüsüne taşınmaz.

## Doğrulama
405 Python testi: 404 başarılı; Windows DPAPI testi Linux ortamında atlandı. JavaScript sözdizimi, 10 davranış grubu ve 6 başsız bütünleşme grubu başarılı. Bütün oturum bekleme türleri, komut zincirinde kullanıcı değişimi, kapanış sonrası bildirim iptali, iç içe gerçek motor bağlamı ve model bağlamının geri gelişi sınandı. Sabah özeti için yakalanan profil, kullanıcı değişiminde sonucun atılması ve kapanış öncesi/sonrası davranış test edildi.

Gerçek Windows, mikrofon, ses donanımı ve tarayıcıdaki görsel yerleşim burada doğrulanmadı. Ağ çağrılarındaki süre etkisi gerçek PC’de ölçülmedi. Ayrıntılı test çıktısı: `MAIN_PAKET_TEST_SONUCU.txt`. Önceki kontrol notları tarihsel test sayılarını içerir; bu ZIP’in güncel sonucu 405 testtir. main.py içindeki ana döngü ve eski işleyicilerin tamamı modüllere taşınmış değildir.
