# Smart Router ve görev ajanları · 7 Ekim 2026

> Tarihsel kayıt: Bu belgedeki eski sağlayıcı sırası/OpenRouter/ücretli vendor seçimi güncel hedef değildir.14 Kasım2026 Router V2 ve uygulama/emeklilik haritası geçerlidir: [güncel mimari](architecture/JARVIS_ROUTER_ARCHITECTURE_V2.md), [uygulama/kabul](architecture/JARVIS_ROUTER_V2_IMPLEMENTATION_AND_RETIREMENT_MAP.md).


Ayarlar > Bağlantılar bölümünde Smart Router anahtarını/ücretsiz hesap seçimini kaydet; Ayarlar > Yapay zekâ bölümünde Smart Router seç. Sohbetten `smart router aç` da aynı seçimi yapar. Mevcut elle seçilmiş sağlayıcı değişmez.

API anahtarı tek başına hesabın ücretsiz olduğunu kanıtlamaz. Gemini/Groq otomatik havuzuna yalnız kullanıcı bu hesapların ücretsiz planda ve ücretli faturalamasının kapalı olduğunu doğrulayınca girer. Jarvis hesap faturalamasını uzaktan doğrulayamaz. Kota/bağlantı hatasında sonraki sağlayıcı denenir; hata veren sağlayıcı 60 saniye bekletilir. Otomatik modda Gemini ücretsiz hesap doğrulaması yoksa Gemini Live, Gemini STT, gömme ve arka plan model kontrolü de buluta çağrı yapmaz. Normal gizlilik modunda ses için mevcut ücretsiz Google web STT kullanılır; yerel/gizli modda web STT de kapalıdır. OpenAI/Claude hiçbir zaman otomatik fallback değildir; mevcut açık kullanıcı seçimiyle çalışır.

| Görev | Otomatik tercih sırası |
|---|---|
| Kısa sohbet | Groq, Gemini, Ollama |
| Kod | Gemini, Groq, Ollama |
| Uzun metin/analiz | Gemini, Groq, Ollama |
| Görüntü | Gemini, Ollama |

Anahtarı/doğrulaması bulunmayan sağlayıcılar atlanır. Ollama seçili modelinin yerelde bulunması gerekir; görüntü için model ayrıca görüntü desteklemelidir. Yerel gizlilik modu buluta çıkmaz. Gizli modda görüntü ve web ajanı kapalıdır. Sıralama görev profiline dayalı bir politikadır; model kalite benchmark'ı veya daha iyi yanıt garantisi değildir. OpenRouter ücretsiz router, istekteki özellikleri destekleyen ücretsiz modelleri süzer.

`router durumu` son seçimi ve yetenek tablosunu gösterir. Anahtarlar kullanıcıya özel korumalı tutulur. Durum ve hata izleri anahtar/prompt içermez.

## Görev yürütücüsü

Sohbete `görev: https://example.com sayfasını araştır, Türkçe rapor hazırla ve dosyayı doğrula` yaz. Model en çok 8 adımdan oluşan bağımlılık planı üretir. Gerçek işçiler sırasıyla çalışır:

- Araştırma ajanı gerçek URL içeriğini indirir, kaynağı rapora taşır.
- Yazı ajanı önceki çıktıları kullanarak Markdown raporu üretir, dosyayı kaydedip geri okuyarak doğrular.
- Tarayıcı ajanı gerçek sayfadaki kontrolleri görür; URL, tıklama, metin, seçim, tuş ve ekran görüntüsü işlemlerini yürütür.
- Kod ajanı açık ve şifresi çözülmüş geliştirme modunu kullanır. Taslak/otomatik uygulama tercihi geliştirme modundaki mevcut kullanıcı ayarına bağlıdır.
- Doğrulama ajanı bağımlı görev çıktılarının/dosyalarının varlığını kontrol eder; raporun tüm iddialarını bağımsız bilimsel doğrulamayla onayladığı anlamına gelmez.

`görev durumu` son görev adımlarını, kayıtlı çıktıları ve dosyaları getirir. Hata sonrası bağımlı görevler engellenir; başarısız, iptal edilmiş veya kesilmiş iş tamamlandı sayılmaz. Tarayıcı onayı sonrasında aynı görev devam eder. Yarım kalmış tarayıcı onayı varken yeni görev başlamaz. Kesilmiş görevler sessizce yeniden uygulanmaz.

## Tarayıcı kurulumu ve kullanım

`kurulum.bat`, Playwright ve Chromium dahil tüm Jarvis paketlerini birlikte hazırlar. Kendi oturumunu kullanacaksan `scripts/tarayici_oturumu.bat` ile Jarvis'in ayrı tarayıcı penceresine giriş yap ve kapat. Şifreyi tarayıcıya kendin gir. Sohbet veya modele verme. Chrome'daki mevcut kişisel profil otomatik devralınmaz.

`tarayıcı görevi: https://example.com sayfasını aç, başlığı oku` örneği gerçek sayfayı okur. Form doldurma/tıklama/seçim/tuş planı URL ve tam adımlar gösterilerek onaya gelir. `tarayıcı onayla KIMLIK` tam gösterilen planı uygular; `tarayıcı iptal` bekleyen planı siler. Onay kullanıcıya ve sayfa/hedef parmak izine bağlıdır, 10 dakika geçerlidir. Sayfa/hedef değişirse uygulanmaz. Onay, etki öncesinde tüketilir; tekrar isteği aynı planı yeniden göndermeye izin vermez.

Alan değerleri geri okunur. Tıklama/tuş/seçim için modelin belirlediği beklenen URL/metin doğrulanır. Tıklama/tuşta yeni sonuç görünmezse başarı ilan edilmez. Siteye özgü seçiciler, CAPTCHA, MFA, SPA oturumları veya dinamik sayfalar hata verebilir; sistem bu durumda sonucu belirtir. Ekran görüntüsü kaydedilir ve sohbet geçmişinde yeniden görüntülenebilir.

## PC ve ses kontrolü

Sohbete `pc ses kontrolü` yaz. Python, Windows, ses/tarayıcı paketleri, mikrofon/hoparlör aygıtları ve Node durumunu salt okunur sorgular. Aygıt bulunduğu için canlı mikrofon/uyandırma/TTS doğrulandı demez. JSON tanılama raporu kaydedilir. Görev sonuçları canlı ses akışında kısa bildirilir; ayrıntı sohbet ekranında kalır.

Otomatik kontroller `scripts/run_tests.bat` içinde. Bu paketin hazırlandığı Linux ortamında gerçek Windows pencere/klavye işlemleri, mikrofon/hoparlör ve gerçek kullanıcı model anahtarları doğrulanmadı. Chromium indirmesi ortamda geçersiz/eksik ZIP döndüğü için gerçek Chromium uçtan uca testi çalıştırılamadı; tarayıcı izin/hedef/plan/doğrulama akışları taklit adaptörlerle test edildi. Bu sınırlamalar çalışan gerçek tarayıcı veya donanım testleri gibi sunulmaz.

Resmî API referansları: [Playwright Python kurulum](https://playwright.dev/python/docs/library), [Groq Chat API](https://console.groq.com/docs/api-reference).
