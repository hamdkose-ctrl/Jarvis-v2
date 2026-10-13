# Jarvis eklenti ve kurulum analizi

Kaynak incelemesi: 10 Ekim 2026. PC'deki gerçek kurulum listesi bu kaynaktan görülemez; kurulum sonunda `.jarvis/kurulum_raporu.json` oluşur. Bu rapor anahtarları, konuşmaları ve eklenti kaynaklarını içermez.

| Parça | Kaynakta durum | Tek kurulumda işlem |
|---|---|---|
| Çekirdek Python paketleri | requirements.lock.txt altında sabit | Aynı sürümler kurulur; kilit elle değiştirilmez |
| Hey Jarvis | openwakeword + ONNX kodu mevcut; ayrı uyandırma betiği vardı | ONNX modelleri indirilir ve yüklenerek doğrulanır |
| Yerel Türkçe STT | faster-whisper small/base, taslak PR #42 | Paket ve small modeli hazırlanır; ses tercihi değişmez |
| Belge dönüşümü | MarkItDown ayrı süreçte kullanılıyor; eksikse eski okuyuculara düşüyordu | Word/Excel/PowerPoint eklentileriyle kurulur |
| Tarayıcı ajanı | Playwright bağımlılıkları requirements-browser.txt içinde; eski ayrı kurulum kaldırıldı | Playwright + Chromium aynı kurulumda hazırlanır |
| Gemini/Groq/OpenRouter | Sağlayıcı kodları mevcut | Paket kurulumu hesap/anahtar eklemez; mevcut kullanıcı ayarı korunur |
| Google e-posta/takvim | Google API paketleri kilitte | OAuth hesabı kullanıcı tarafından bağlanır; kurulum yapmaz |
| Ollama | Router yerel modeli kullanabiliyor | Harici Ollama uygulaması ve yüklü modeller raporlanır; bu kaynak paketi onları taşımaz |
| Windows sesi | pyttsx3 mevcut | Çekirdek ortamdan kurulur; Piper bu sürümde yok |
| Kişisel Jarvis eklentileri | `.jarvis/plugins/*.py`, kaynak ZIP'inde yok | Dosya adları, statik import listesi ve handle varlığı raporlanır; otomatik çalıştırılmaz/kurulmaz |

## Önceden konuşulan geliştirme araçları

Claude Code/Setup, Claude-Mem, Task Observer, Headroom ve OmniRoute Jarvis'in Python bağımlılıkları değildir. Claude'a geliştirme ortamı, hafıza, bağlam sıkıştırma veya sağlayıcı yönlendirme sağlarlar. Bunları kurmak Jarvis'in kendi router/ses modüllerini otomatik değiştirmez. Bu kurulum Claude ayarlarına, sağlayıcı anahtarlarına ve port yönlendirmelerine dokunmaz.

Task Observer'ın proje `.claude` ve CLAUDE.md dosyaları kullanıcı tarafından silindi; burada yeniden oluşturulmadı. Claude-Mem/Headroom gibi kullanıcı genelindeki ayarların gerçekten durduğu, kaynak dosyasından doğrulanamaz. PATH'te bulunabilen git/node/ollama/claude/omniroute/headroom araçları raporda yalnız var/yok olarak listelenir; PATH dışında kurulmuş araçlar "yok" görünebilir.

`modules/plugins.py` özel Python eklentilerini doğrudan import ediyor; bu bir sandbox değildir. Tek kurulum bu eklentileri otomatik import etmez veya import adlarından rastgele pip paketi kurmaz. Rapordaki import adı her zaman PyPI paket adı değildir.

## Tek kurulum

Jarvis kapalıyken kökteki `kurulum.bat` çalıştırılır. Python'ın kurulu olması gerekir. Paket ve model indirmeleri internet kullanır; bu ZIP çevrimdışı model arşivi değildir. Kurulum paketleri hazırlar, mevcut ses/model/gizlilik tercihini otomatik değiştirmez.

Başarısız bağımlılık, Chromium veya model hazırlığında çalışan `.venv` korunur. Eksik Whisper modeli önce geçici klasöre indirilir ve yerel tokenizer ile yüklenerek doğrulanır; sonra hedefe alınır. Mevcut geçerli model tekrar indirilmez. Yeni ortam doğrulandıktan sonra devreye alınır; önceki ortam `.venv_backup` altında korunur. Kurulum sonunda kaynak önbellekleri ve bilinen eski arayüz dosyaları temizlenir; günlükler/model dosyaları/veriler korunur.

Eklerin kesin sürümleri ilk başarılı PC kurulumundan sonra çalışan ortamdan sabitlenmelidir. Burada tahmini lock sürümü yazılmadı. Windows/Python 3.14 kurulum ve mikrofon denemesi ayrıca yapılmalıdır.
