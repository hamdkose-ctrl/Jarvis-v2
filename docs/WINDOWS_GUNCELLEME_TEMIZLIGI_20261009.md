# Windows Güncelleme Test Klasörü Kilidi

Gözlenen hata: `PermissionError: [WinError 32]` ve `jarvis-trusted-tests-…/project` yolu. Bu klasör aday sürümün mevcut testlerle doğrulanması için oluşturulur. Klasörün temizlenmesi sırasında Windows paylaşım kilidi oluşması, önceki kodda test sonucunun yerine istisna döndürüp güncellemeyi durdurabiliyordu. Kilidi tutan süreç ekrandaki hata mesajından belirlenemiyor.

Geçici aday, güvenilir test ve test verisi klasörleri artık ortak bir temizlik yordamı kullanır. Windows paylaşım ihlallerinde (32/33) temizlik sınırlı sayıda yeniden denenir. Kilit devam ederse uyarı kaydedilir ve yalnız bu geçici klasörün temizliği ertelenir. Klasör geçici dizinde kalabilir; güvenlik denetimleri veya gerçek test hataları atlanmaz. Başka disk/izin hataları sessizce yutulmaz. Salt okunur kopyaların silinmesi için Windows erişim hatasında yazılabilirlik yeniden denenir.

Bu düzeltme kurtarma/test altyapısındaki korunan dosyaları değiştirir. Eski kurulumun otomatik güncelleyicisi bu dosyaları değiştiremez. İlk kurulum için Jarvis tamamen kapatılmalı ve güncel tam ZIP içindeki Jarvis klasörünün içeriği mevcut program klasörüne kopyalanmalıdır. Mevcut klasör silinmemeli; `.venv`, anahtarlar ve kişisel veriler korunmalıdır. Program açıldıktan sonra Araçlar → GitHub → Gerçek Durumu Doğrula, kaynakların GitHub ile eşleştiğini kontrol eder.

Testler Windows paylaşım ihlalini taklit ederek geçici ve kalıcı kilidi, gerçek test hatasının korunmasını ve aday testlerin başarılı/başarısız sonucunun değişmemesini doğrular. Gerçek Windows bilgisayarında tekrar kontrol gerekir.
