# Geliştirme Atölyesi kaldırıldı

Atölye menüsü, sayfası, sohbet/plan/görsel önizleme API'leri ve otomatik kaynak kod geliştirme komutları kaldırıldı. GitHub yükleme/güncelleme işlemleri bağımsız modules/git_publish.py modülüne taşındı. Normal sohbet, dosyalar, öğrenme, PC/telefon eşleştirme ve mikrofon kontrolü korunur.

Kurulum: Jarvis'i kapatın. Bu paketin Jarvis klasöründeki dosyaları mevcut kurulumun üzerine çıkarın. `baslat.bat` ile açın; eski paketlerde kalmış modül/arayüz dosyaları ve gereksiz kaldırma BAT'ı otomatik silinir. Ayrıca bir temizleme BAT'ı çalıştırmanız gerekmez. Kopyalama tek başına silinmiş dosyaları kaldırmadığından bu adım gereklidir.

Kaldırma betiği yalnız kendi kurulum klasöründeki belirtilen eski kaynakları temizler. Kişisel veri klasöründeki not, anahtar ve geçmiş kayıtlarını silmez. Önceki yerel kaynak değişiklikleri için güncelleme koruması korunmuştur. Eski sürüm notlarındaki atölye açıklamaları tarihsel kayıttır; özellik bu sürümde bulunmaz.

Doğrulama: 3 kaldırma/temizlik testi, 5 JavaScript davranış grubu ve headless smoke başarılı. Tam Python grubu 173 testte eski aynı 7 ortam hatasıyla tamamlandı; yeni başarısızlık yok (Windows DPAPI/font, pyautogui ve ağ arayüzü erişimi). Canlı Windows kurulumu burada denenmedi.
