> NOT: Bu rapor önceki denetimin tarihsel kaydıdır. Güncel GitHub ve kullanıcı/API mimarisi için ../README.md, ATOLYE_KALDIRILDI.md ve GITHUB_AKISI.md geçerlidir.

# JARVIS V2 — Kod, Performans ve Güvenlik Denetimi

Tarih: 2026-10-05

Bu rapor yüklenen kaynak paketinin statik incelemesi ve bu ortamda yapılabilen otomatik testlere dayanır. Windows mikrofonu, kamera, gerçek Ollama, Gemini/Groq ağı, Tailscale, telefon ve masaüstü GUI'si fiziksel Windows makinede uçtan uca çalıştırılmadı.

## Sonuç özeti

Kaynak paketinde kritik görünen ana kararlılık problemi Self-Coder tarafındaydı. Self-Coder proje kökünü `rglob()` ile tarıyor ve `python -m compileall -q .` çalıştırıyordu. Gerçek kurulumda proje kökünde `.venv` bulunduğundan, filtre sonradan uygulansa bile tarama `.venv` içine giriyor; `compileall` da sanal ortamı derleyerek yoğun disk/CPU kullanımı, çok sayıda `__pycache__`, uzun bekleme ve zaman aşımı oluşturabiliyordu. Bu davranış kaldırıldı.

İkinci önemli problem Self-Coder'ın başarılı sonucu bile hata gibi işaretleyebilmesiydi. Başarılı mesajın içinde “geri al” ifadesi bulunduğu için `main.py` genel kelime aramasıyla sonucu başarısız sayıyordu. Hata belirleme artık yalnız gerçek rollback/başarısızlık ifadelerine bakıyor.

Üçüncü önemli mimari sorun GitHub yedeğinin canlı kaynak gibi kullanılmasıydı. Açılışta otomatik güncelleme ve Self-Coder'ın başarılı değişikliği otomatik GitHub commit/push akışı, yedek depo ile aktif çalışma kopyasını birbirine bağlıyordu. Bu hem iki bilgisayarda sürüm ayrışması hem de Self-Coder sırasında ağ gecikmesi/çökme hissi yaratabilirdi. GitHub artık varsayılan olarak yalnız yedek/manüel güncelleme kaynağıdır; Self-Coder otomatik push yapmaz.

## Düzeltilen Self-Coder sorunları

- `.venv`, `venv`, `node_modules`, `.git`, `__pycache__`, yedek ve test cache klasörleri tarama sırasında tamamen budanıyor; içine hiç girilmiyor.
- `compileall` yerine yalnız proje `.py` kaynaklarını bellekte `compile()` ile kontrol eden kaynak derleme testi eklendi. `.pyc` üretmiyor.
- Self-Coder'ın çalıştırabileceği test komutları tam olarak iki komutla sınırlandı: güvenli kaynak derleme ve yerleşik `unittest` keşfi. Keyfî `pytest` argümanları ve haricî yollar artık kabul edilmiyor.
- Büyük dosyalarda yalnız ilk 28–35 bin karakteri göndermek yerine görev anahtar kelimelerinin çevresindeki kod parçaları seçiliyor; toplam bağlam sınırlandırıldı.
- Çekirdek/güvenlik dosyaları (`main.py`, `web.py`, `config.py`, `gui.py`, `updater.py`, telefon, privacy, system_control ve Self-Coder dosyaları) değişirse risk otomatik `high` oluyor ve açık yüksek-risk onayı gerekiyor.
- Self-Coder başarılı değişiklikten sonra GitHub ağına bağlanmıyor. Değişiklik yalnız yerelde korunuyor.
- Self-Coder yedekleri 15 adetle sınırlandı; sınırsız büyüme engellendi.
- Başarılı Self-Coder sonucunun “geri al” kelimesi yüzünden hata gibi görünmesi düzeltildi.

## Performans düzeltmeleri

- Kullanılmayan `three.min.js`, `world.js` ve eski `webui/earth/` 3B doku klasörü kaldırıldı. Aktif arayüz bunları çağırmıyordu.
- `nx.html` içindeki gereksiz Three.js/world script yükleri kaldırıldı.
- Ana arayüzün sürekli canvas/globe çizimi yaklaşık 30 FPS'ten 20 FPS'e düşürüldü. Arka planda sekme gizliyken zaten çizim yapılmıyordu; bu davranış korundu.
- Tüm paketlenmiş `__pycache__`, `.pyc` ve `.pytest_cache` dosyaları temizlendi.
- Self-Coder proje taraması ve sağlık kontrolü kaynak dosyalara sınırlandı; `.venv` kaynak tüketimi ortadan kaldırıldı.

## Güvenlik düzeltmeleri

- Normal `jarvis.log` içine tam kullanıcı komutu yazılması yerine `privacy.redact(..., force=True)` ile hassas bilgiler maskeleniyor ve kayıt uzunluğu sınırlandırılıyor.
- Yerel web arayüzü zaten `127.0.0.1` ile sınırlı ve Host + oturum token kontrolü kullanıyordu. Buna `Referrer-Policy: no-referrer`, `X-Content-Type-Options: nosniff` ve `X-Frame-Options: DENY` başlıkları eklendi.
- Yerel web API'sinde 2 MB sınırını aşan JSON istekleri artık kesilip kısmi okunmak yerine 413 ile reddediliyor.
- Telefon sunucusunda yeni oluşturulan token uzunluğu 9 byte yerine 24 byte rastgele veri olacak şekilde artırıldı. Var olan token kendiliğinden değiştirilmez; mevcut telefon bağlantısı bozulmaz.
- Telefon API'sine IP bazlı basit yetkisiz-deneme sınırlaması eklendi: 60 saniyede 8 başarısız token denemesinden sonra geçici 429 döner.
- Telefon yanıtlarına `no-store`, `no-referrer`, `nosniff`, `DENY` güvenlik başlıkları eklendi.
- Telefon `/api/ask` ve `/api/send` POST gövdeleri artık sınırı aşınca kısmi okunmuyor; doğrudan reddediliyor.
- Kaynak paketinde gerçek API anahtarı/deseni bulunmadı.

## GitHub / iki-PC mimarisi

Bu sürümde GitHub canlı çalışma kaynağı değildir.

- `updater.check()` açılışta ancak `settings.json` içinde `auto_update: true` açıkça verilmişse otomatik çalışır. Varsayılan kapalıdır.
- Arayüzdeki “Güncelleme var mı?” manüel kontrol `force=True` ile çalışır.
- GitHub token kaydetmek güncellemeyi otomatik tetiklemez.
- Self-Coder GitHub'a otomatik commit/push yapmaz.
- Self-Coder değişiklikleri `~/.jarvis/selfcoder/local_changes.json` ile yerelde korunur; manüel updater bu dosyaların üzerine yazmaz.

Bu yapı Ev ve İş PC'nin aynı kod tabanını kullanmasına uygundur; ancak sürüm aktarımı şimdilik otomatik senkronizasyon değildir. Tek Gateway / ortak güncelleme mekanizması daha sonra ayrı bir katman olarak yapılmalıdır.

## Claude temizliği

Önceki kaynakta Claude sağlayıcısı hâlâ UI, `config.py`, `llm.py`, teşhis ve öğrenme metinlerinde bulunuyordu. Claude çalışma yolları ve arayüz öğeleri kaldırıldı. Desteklenen sağlayıcılar artık Gemini, Groq ve Ollama'dır.

Eski kurulumdan kalabilecek `~/.jarvis/claude_key.txt` dosyası bu paket tarafından silinmez. Self-Coder blok listesinde kalır; bu bilinçli bir güvenlik önlemidir.

## Modül ayrışması ve bağlantılar

Ana akış şu şekilde:

`gui.py` → varsayılan web Komut Merkezi `web.py` → motor `main.py` → router/LLM/araç modülleri.

- `main.py`: komut yürütme ve orkestrasyon merkezi.
- `modules/router.py`: komut sınıflandırma/intent ayrımı.
- `modules/llm.py`: Gemini/Groq/Ollama sağlayıcı katmanı.
- `modules/selfcoder/engine.py`: Self-Coder planlama, onay sonrası uygulama, test ve rollback.
- `modules/selfcoder/publish.py`: artık ağ yayını değil, yerel değişiklik koruma kaydı.
- `modules/phone.py`: telefon HTTP erişimi.
- `web.py`: yalnız localhost Komut Merkezi API/UI sunucusu.
- `updater.py`: GitHub yedeğinden manüel/isteğe bağlı güncelleme.

59 Python modülü statik olarak kontrol edildi. Fonksiyon içi/lazy importlar dahil edildiğinde karşılıklı referanslar görülüyor, ancak **üst-seviye import grafiğinde döngü bulunmadı**. Bu nedenle açılışta klasik circular-import zinciri tespit edilmedi. Klasik Tk arayüz dosyaları (`pages.py`, `pages2.py`, `panel.py`, `chatview.py`, `theme.py`) varsayılan web arayüzü başarısız olursa fallback olarak hâlâ kullanıldığı için silinmedi.

## Temizlenen gereksiz dosyalar

- tüm `__pycache__/`
- tüm `.pyc`
- `.pytest_cache/`
- kullanılmayan `webui/three.min.js`
- kullanılmayan `webui/world.js`
- kullanılmayan `webui/earth/` texture klasörü
- artık kullanılmayan `CLAUDE.md`

Kaynak paket yaklaşık 4 MB sınıfından yaklaşık 2 MB sınıfına indi; son ZIP sıkıştırması ayrıca küçültecektir.

## Testler

Bu ortamda yapılan kontroller:

- 59 Python kaynak dosyasının tamamı bellekte `compile()` kontrolünden geçti: **0 syntax hatası**.
- `python -m unittest discover -s tests -q`: **4/4 test geçti**.
- `webui/nx.js`, `earth.js`, `icons.js`: Node sözdizimi kontrolünden geçti.
- Self-Coder güvenli test koşucusu smoke test: kaynak derleme + 4 unittest **başarılı**.
- Self-Coder güvenli komut filtresi: `pytest -q` ve haricî yol içeren unittest komutu **reddedildi**.
- `updater.check()` temiz ayarda ağ çağrısı yapmadan `None` döndü; `auto` durumu **False**.
- Yeni telefon tokenı smoke testte 32 karakter URL-safe çıktı ve yeniden okumada aynı token korundu.
- Top-level Python import grafiğinde **0 döngü**.

Bu Linux/sandbox ortamında `google-genai` paketi kurulu olmadığı için gerçek LLM Self-Coder plan çağrısı yapılmadı. Self-Coder'ın ağdan bağımsız sağlık/test fonksiyonları stub LLM ile ayrıca çalıştırıldı.

## Kalan riskler / sonraki iş

1. **Telefon LAN modu hâlâ düz HTTP kullanıyor.** Token güçlü olsa da aynı ağdaki kötü niyetli trafik izleme teorik olarak tokenı görebilir. Tailscale Serve HTTPS kullanıldığında risk ciddi azalır. Varsayılanı zorla Tailscale yapmak mevcut telefon kullanımını kırabileceği için bu sürümde değiştirilmedi.
2. **`phone_token.txt` düz metin tutuluyor.** Mevcut mobil köprü bu dosyayı okuyabildiği için bu sürümde şifrelenmedi. Tek Gateway'e geçerken token saklama DPAPI ile yapılmalı ve mobil köprü aynı API üzerinden kimlik doğrulamalı.
3. Siri GET endpoint'i uyumluluk için `?k=` query tokenını destekliyor. Kestirme geçmişinde görünme riski var. Yeni mobil uygulama `X-Token` kullanmalı; tek Gateway'de GET-token yolu yalnız Siri uyumluluk modu olarak izole edilmeli.
4. **v5.12 ile giderildi:** `git yükle` sırasında çalışan JARVIS `.venv` ortamı `requirements.lock.txt` dosyasına sabitlenir; `kurulum.bat` lock varsa onu kullanır. Böylece Ev/İş PC aynı paket sürümlerini kurabilir.
5. İlk açılışta GUI'nin Gemini anahtarı isteme yolu anahtarı kısa süre düz dosya olarak yazıp `config.py` yüklenince DPAPI biçimine geçiriyor. Kalıcı depoda koruma var, fakat bu ilk-yazım penceresi daha sonra ayrıca kapatılabilir.
6. Self-Coder hâlâ bir LLM yanıtını senkron bekler; ağ/sağlayıcı yavaşsa komut kuyruğu o süre boyunca meşgul olur. `.venv`/compileall ve GitHub push kaynaklı kilitlenmeler kaldırıldı, ancak tam “iptal edilebilir Self-Coder işi” için ileride ayrı job/worker katmanı önerilir.
7. Bu paket gerçek Windows donanımında çalıştırılmadı. Özellikle mikrofon, Live, Vision, Tailscale, telefon ve Self-Coder'ın gerçek Gemini/Groq çağrısı Windows'ta regresyon testine tabi tutulmalıdır.

## Öncelikli gerçek-PC test sırası

1. Jarvis normal açılış → Komut Merkezi.
2. Basit sohbet + Groq/Gemini + Ollama fallback.
3. Telefon sunucusu yalnız yerel Wi-Fi'da bağlantı ve yanlış-token limit testi.
4. Self-Coder: yalnız düşük riskli, tek satırlık test değişikliği → plan → onay → derleme + unittest → rollback.
5. Self-Coder inceleme modu → CPU/disk kullanımını Görev Yöneticisi'nden izleme; `.venv` altında yeni `__pycache__` oluşmadığını kontrol.
6. Manüel GitHub “Güncelleme var mı?” testi; açılışta otomatik güncelleme olmadığını doğrulama.
7. Ev/İş iki kurulumda aynı sürüm hash'ini doğrulama; daha sonra tek Gateway tasarımına geçme.

### Ek telefon sertleştirmesi
Telefon token dosyası mevcut köprü uyumluluğu bozulmadan dosya izinleri/Windows ACL ile sınırlandırıldı. HTTP yanıtlarına CSP ve Permissions-Policy eklendi; sunucu thread/kuyruk davranışı sıkılaştırıldı.
