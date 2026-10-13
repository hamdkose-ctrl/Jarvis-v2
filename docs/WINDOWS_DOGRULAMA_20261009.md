# Windows Yayın Doğrulaması

Ekrandaki engel test_safe_updater testinin Windows üzerinde gerçek sembolik bağlantı oluştururken WinError 1314 almasıdır. Test, yalnız bu izin hatasında açıklamalı olarak atlanır. Diğer OSError hataları başarısızlık olarak kalır. Sembolik bağlantı oluşturabilen ortamlarda gerçek dosya güvenlik testi çalışmaya devam eder. Güncelleme güvenliği ve zorunlu JavaScript/Python testleri değiştirilmedi.

Gerçek dosyalarla 8 güncelleme testi çalıştırıldı. WinError 1314 benzetiminde açıklamalı atlama ve diğer dosya hatalarının gizlenmediği ayrıca kontrol edildi. Fiziksel Windows cihazında tekrar çalıştırılması henüz doğrulanmadı. Önceki mobil, ana ekran bağlantısı ve kompakt sohbet değişiklikleri dahildir. Android APK yoktur.

PC’de önce Jarvis’i kapatın. Yeni paketi mevcut proje dosyalarına uygulayıp yeniden açın; aynı klasörden GitHub’a yüklemeyi tekrar deneyin. Kullanıcı ayarları ve anahtarları silmeyin.
