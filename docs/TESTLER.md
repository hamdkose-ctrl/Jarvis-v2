# Testleri çalıştırma

Windows'ta `run_tests.bat` dosyasını çalıştır. Hata varsa komut başarısız çıkar; başarısız veya çalıştırılmamış bir grup yeşil sayılmaz.

Bu proje Python testlerinde standart kütüphanedeki `unittest` kullanır. `pytest` kurulması gerekmez. Python testleri mevcut `.venv` ortamında, kişisel profil ve anahtar deposundan ayrı geçici verilerle çalışır. Ardından beş motor bütünleşme denemesi ve yedi JavaScript davranış grubu çalışır. Masaüstü erişim grubu URL dışında anahtar taşıma ve oturum kurulumunu denetler. Asıl script `scripts/run_tests.bat` içindedir; kökteki dosya uyumlu bir başlatıcıdır.

Python testlerini tek başına çalıştırmak için:

```powershell
$env:JARVIS_DATA_DIR = "$env:TEMP\jarvis-tests"
.venv\Scripts\python.exe -X utf8 -m unittest discover -s tests -q
```

JavaScript testleri Node.js gerektirir. Başlatıcı önce sistemdeki Node.js'i, bulunamazsa mevcut Codex çalışma ortamındaki Node.js'i kullanır. İkisi de yoksa açıklama verip başarısız çıkar.

Testler donanımı, canlı model yanıtlarını ve uzak telefon bağlantısını taklit eder. Gerçek mikrofon/hoparlör ve HTTPS/Tailscale telefon denemesi ayrıca yapılmalıdır.


## 7 Ekim 2026 test düzeltmesi

- Testler sahte Google SDK'sını `sys.modules` içine kalıcı olarak eklemez. `google-genai` gerçek kurulum bağımlılığıdır; eksikse hata görünür kalır.
- YouTube anahtarının kayıt, geçiş, silme ve atomik yazma testleri geçici bir koruma adaptörü kullanır. Gerçek DPAPI testi yalnız Windows'ta çalışır; diğer sistemlerde açıkça atlanır. Üretimdeki Windows anahtar koruması değiştirilmedi.
- Telefon güvenlik testleri Tailscale IP keşfini test boyunca taklit eder; gerçek ağ arayüzü izinlerine bağımlı değildir. Yerel HTTP istekleriyle kimlik doğrulama denemesi devam eder.
- Bakım bütünleşme testi ekran/klavye bağımlılığını diğer headless testler gibi taklit eder.
- Türkçe PDF yazımı Windows fontlarını öncelikli kullanır; Linux/macOS'ta uygun Unicode fontu arar. Font yoksa eksik harfli çıktı üretmez ve mevcut hedef dosyayı korur.

Linux doğrulaması: 202 test, 201 başarılı, 1 Windows DPAPI testi atlandı; dört motor bütünleşme denemesi ve altı JavaScript grubu başarılı. Canlı API ve gerçek donanım denenmedi.


## Şifreli geliştirme modu doğrulaması

Son sonuç: 229 Python testi, 228 başarılı ve 1 Windows DPAPI testi atlandı. 5 motor bütünleşme denemesi ve 7 JavaScript grubu geçti. Geliştirme testleri gerçek geçici dosyalarda taslak, revizyon, uygulama, geri alma, yarım işlem kurtarma, kayıt hatası, kullanıcı ayrımı, şifre, görsel referans, eski görsele erişim ve dışa aktarmayı sınar. Gerçek Bridge ve canlı ses araç sarmalayıcısı ayrıca model taklitleriyle denendi. Mobil JavaScript testi Python'un gerçekten ürettiği HTML'i kullanır.

Kullanım: [GELISTIRME_MODU](GELISTIRME_MODU.md).
