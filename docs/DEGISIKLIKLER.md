# 6 Ekim 2026 — Çökme ve sohbet çevirisi düzeltmesi

- Ana sayfanın boş kalmasına neden olan JavaScript başlatma hatası giderildi: not ekleme olayı, olay tablosu oluşturulduktan sonra tanımlanıyor.
- Metin çevirisi artık sohbet içinde gösteriliyor; uzun sonuçlar otomatik dosya kaydına yönlendirilmiyor.
- Önceki özgün kullanıcı metni çeviri komutlarında korunuyor; Türkçeye ve İngilizceye çevir düğmeleri birlikte sunuluyor.

# 6 Ekim 2026 — Kamera, kaynakla çalışma ve ortak takvim

Kamera önizlemesi eklendi. Seçili kaynak, konu alanı boşken çalışmayı başlatır; kaynağa bağlı soru önerileri gösterilir. Veri Klasörü Araçlar'a taşındı. Takvim/görevler aylık ve günlük görünümde birleşti. Ana sayfada notlar gösterilir. Ayrıntılar: UYGULAMA_OZETI.md.

# 2026-10-06 — Birleştirme, Self-Coder log düzeltmeleri ve mobil erişim
- Baz: `JARVIS-main-Git-Calisma-Guncel.zip`. Sonraki Çalışma/Git düzenlemeleri korunarak telefon ve başlangıç düzeltmeleri birleştirildi.
- Logdaki `ses seviyesini 20 yap` komutunun 2 numaralı öneri sayılması düzeltildi. Kısa öneri seçimleri artık tam cümle; uzun seçimlerde öneri/geliştirme adı zorunlu.
- Bekleyen Self-Coder planı bağımsız ses/hava/sohbet komutlarını engellemez. Kodun amacı sorulduğunda görev, dosyalar, gerekçeler ve risk somut olarak açıklanır; açıklama uygulama onayı değildir.
- `find metni 0 kez bulundu` hatasında güncel kaynak kesitleriyle bir kez yeni plan istenir. Birebir tek eşleşme, izin verilen yollar, yedek/test/rollback ve açık uygulama ifadeleri korunur.
- Self-Coder kaynak kesitlerindeki yapay satır numaraları kaldırıldı; CRLF/LF farkları normalize edildi. Ana ekran görevlerinde nx.js/nx.css/nx.html/web.py bağlamı önceliklidir.
- PC telefon QR’ı 90 saniyelik ve tek kullanımlıktır; kişisel API anahtarı taşımaz. QR yenileme, profil seçimi ve gerçek yakın-zamanlı telefon bağlantı göstergesi eklendi.
- Android/iOS ortak mobil web arayüzüne manifest, PNG simgeler, kurulum düğmesi ve çevrimdışı bağlantı yardım ekranı eklendi. API/sohbet/anahtarlar service worker önbelleğine yazılmaz.
- Mobil gönderim başarısızsa yazılan metin korunur. Sekme gizlenince veya kapanınca mikrofon bırakılır; gecikmeli mikrofon izni eski kayıt başlatamaz. Fotoğraf çözümlemesine ImageBitmap dışı tarayıcı yolu eklendi.
- Android kaynak sürümü 3.0.8: ses parçaları benzersiz kimliklerle izlenir, eski/duble callback yeni konuşmayı bitiremez; stop/başlatma hatasında kuyruk serbest bırakılır.
- İlk açılıştaki global anahtar penceresi kaldırıldı. Kurulumda lock başarısız olursa temiz ortamla serbest kuruluma geçilir; başlatıcı uygulamanın hata kodunu korur.
- Eski arayüz testleri güncel görünüme taşındı ve unittest yayın akışına dahil edildi. Doğrulama ayrıntıları: `UYGULAMA_OZETI.md`.

# 2026-10-05 — Çalışma Modu: derslerim, soru çözme, ders programı, görsel/video
- Çıkmış soru kitapçıkları (AÖL/MEB biçimi) ders ders, bütün soruları ve cevap anahtarıyla yapay zekâsız ayrıştırılıyor. Eskiden metnin küçük bir parçası özetleniyor, dersler karışıyordu.
- "Derslerim": analiz yalnız seçilen derslerde yapılıyor (kitap adına göre otomatik öneri, ör. Biyoloji_1 → BİYOLOJİ – 1). Konu etiketleri ders başına tek istekle çıkarılıp saklanıyor.
- "Soru Çöz": çıkmış sorulardan, sınavda sık çıkan ve zayıf olduğun konulardan soru; cevap anahtarıyla anında doğru/yanlış, "Neden?" ile kitaba dayalı açıklama; konu konu başarı tablosu.
- "Bugün öncelik" ve çalışma cevapları artık zayıf/sık çıkan konulara göre yönlendiriyor.
- "Programım": sınav tarihi, günlük süre, günler ve saate göre haftalık program (yapay zekâsız, anında); "Hatırlatıcıları Kur" ile her gün Jarvis hatırlatır.
- Yan panel: anlatılan konuyla ilgili Vikipedi/Wikimedia görselleri; YouTube anahtarı eklenirse konu anlatımı videoları, yoksa "YouTube'da ara" bağlantısı. Gizli/yerel modda internete çıkılmaz.

# 2026-10-05 — Çalışma: kitap ekleme arka planda
- Kitap / çıkmış soru eklemek artık arayüzü bekletmiyor: kaynak arka planda okunuyor, listede "Okunuyor…" olarak görünüyor, bitince kendiliğinden listeye geçiyor. Eskiden büyük PDF dakikalarca okunurken arayüz donuyor, istek yarıda kesilip "eklenmedi" görünüyordu (kitap aslında ekleniyordu).
- PDF'ler ayrı, düşük öncelikli bir süreçte okunuyor; Jarvis'in arayüzü ve sesi bu sırada yavaşlamıyor.
- Aynı kaynak ikinci kez eklenmiyor (tekrar denemek kitabı baştan okutuyordu).
- PDF yazı tipi uyarıları günlüğe yazılmıyor (her kitapta yüzlerce satır).

# 2026-10-05 — Çalışma kaynakları sesli komutta
- "O kitaptan örnek ver", "çıkmış sorulardan sor" gibi dosya adı içermeyen isteklerde Jarvis artık "hangi dosya" diye sormuyor; Çalışma'ya yüklenen kitap ve çıkmış sorulardan cevap veriyor.

# v5.14 — Telefon: kişiye özel anahtar ve yanıt kimliği (2026-10-05)
- Her kullanıcının kendi telefon anahtarı var (Araçlar › Telefon › "Kimin telefonu?"). Kimin konuştuğunu telefonun gönderdiği ad değil anahtar belirler: bir anahtarla başka kullanıcı adına komut verilemez, onun konuşmaları okunamaz.
- Eski ortak anahtar bozulmadı; artık yalnızca sahibine (ilk kullanımda bilgisayardaki kullanıcı) ait. "Anahtarı yenile" bütün anahtarları birlikte yeniler.
- Telefon sorularına ayrı kimlik veriliyor; yanıt metne göre değil bu kimliğe göre bulunuyor (aynı anda iki soru ya da tekrarlanan cümle karışmaz).
- Android kurulum QR'ı değişmedi (süreli eşleştirme sonraki iş).

# v5.13 — Gizlilik düzeltmeleri (2026-10-05)
- Gizli ve yalnızca-yerel modda ses artık hiçbir servise gönderilmiyor (eskiden Google'ın web servisine geçiyordu). Bu bilgisayarda çevrimdışı ses tanıma olmadığı için bu modlarda sesli komut kapalı; Jarvis yazarak söylemeyi hatırlatır.
- Canlı konuşma (Gemini Live) gizli / yalnızca-yerel modda açılmıyor; Jarvis çalışırken moda geçilse de yeni oturum açılmaz.
- Onay bekleyen Self-Coder planı kullanıcıya özel durumlara eklendi; kullanıcı değişince plan, bekleyen mesaj ve düzenleme işi sıfırlanır (başka kişinin "evet"iyle uygulanmaz).

# Kurulum BAT sağlamlaştırması — 2026-10-05
- `kurulum.bat` artık sanal ortamı `activate` etmiyor; tüm pip işlemlerini doğrudan `.venv_install\Scripts\python.exe` ile yürütüyor.
- Kurulum 5 görünür aşamaya ayrıldı ve hata hangi aşamada oluştuysa açıkça gösteriliyor.
- Paket kurulumu geçici `.venv_install` içinde tamamlanıp doğrulandıktan sonra mevcut `.venv` ile yer değiştiriyor; başarısız kurulum çalışan ortamı silmiyor.
- Ayrıntılı hata kaydı `kurulum.log` dosyasına yazılıyor.

# v5.12 — Güvenli senkronizasyon ve bakım
- GitHub durumu artık kayıtlı etikete güvenmek yerine uzak `main` kaynak ağacıyla doğrulanabiliyor; yerel değişiklik / senkron / çakışma ayrımı var.
- `git yükle` ve GitHub düğmesi yayın öncesi gerçek durumu doğruluyor; force-push yok.
- GitHub yayını silinen kaynak dosyalarını da commit'e yansıtıyor.
- Yayın sırasında çalışan JARVIS `.venv` paketleri `requirements.lock.txt` dosyasına otomatik sabitleniyor; Ev/İş kurulumları lock varsa aynı sürümleri kuruyor.
- Eski kısa telefon anahtarı v5.12 ilk çalışmada otomatik olarak yeni güçlü anahtara geçirilir; Telefon ekranına ayrıca manuel yenileme, Tailscale-only kapsamı ve Tailscale HTTPS kontrolleri eklendi.
- Google OAuth için Production akışı arayüze eklendi; kullanıcı Google Cloud'da In production yaptıktan sonra JARVIS 7 günlük Testing uyarısını kapatıyor.
- Ana sayfada aktif kullanıcının Gemini anahtarı yoksa görünür uyarı kartı eklendi.
- Sürüm bazlı dağınık değişiklik/düzeltme notları bu dosyada birleştirildi.
- `pages.py`, `pages2.py`, `panel.py`, `chatview.py` dosyalarına dokunulmadı.

# v5.11 — Cinematic Command Center
- Açık gün batımı teması, yeni ana ekran yerleşimi, saat yanında hava durumu, canlı aktivite/hatırlatma/GitHub paneli.

# Bu pakette eklenenler

- Groq sağlayıcısı (`modules/llm.py`, `config.py`)
- Groq API anahtarını arayüzden kaydetme/test etme/etkinleştirme
- Ayrı Router katmanı (`modules/router.py`)
- `self_code` intent'i ve Self-Coder komut yönlendirmesi
- Kontrollü Self-Coder (`modules/selfcoder/`)
- Kullanıcı onayı olmadan kaynak koda dokunmama
- Yüksek riskte `yüksek riski onaylıyorum` zorunluluğu
- Dosya sistemi yedeği (`~/.jarvis/selfcoder/backups/`)
- Git deposunda HEAD için `jarvis-backup-*` güvenlik dalı oluşturma girişimi
- Güvenli `find -> replace` düzenleme modeli
- Proje dışına çıkma / gizli anahtar dosyalarını değiştirme engeli
- Otomatik `python -m compileall -q .` testi
- Güvenli ek pytest/unittest testlerine izin
- Test/hata durumunda otomatik rollback
- `son self coder değişikliğini geri al` komutu

## Kontroller

- Tüm Python dosyaları `compileall` ile kontrol edildi.
- `webui/pages.js` ve `webui/pages3.js` Node sözdizimi kontrolünden geçti.
- Self-Coder yedek -> değişiklik -> compile testi -> rollback döngüsü geçici dosyayla doğrulandı.

Bu bölüm tarihsel sürüm kaydıdır. Atölye kaldırılmıştır; güncel durum için `ATOLYE_KALDIRILDI.md` dosyasına bak.

## Hız düzeltmesi v2
- Basit selamlaşmalar Router LLM çağrısını atlar.
- Ekran analizi, screenshot ve sistem durumu doğrudan intent'e gider.
- Self-Coder başlangıçta yüklenmez; yalnızca gerektiğinde lazy-load edilir.
- Groq bağlantı zaman aşımı/fallback süresi kısaltıldı.


## v3 komut ayrımı ve başlangıç düzeltmeleri
- `YouTube aç` artık müzik araması/çalması olarak yorumlanmamalı; yalnızca YouTube açılır.
- `müzik aç` Spotify kuruluysa Spotify, değilse mevcut müzik fallback akışını kullanır.
- `ekranı analiz et` Vision'a daha açık görsel analiz talimatıyla gider; CPU/RAM sistem durumu ana cevap olmaz.
- Genel ekran analizi komutu Vision'a belirsiz soru olarak gönderilmez.
- Hey Jarvis modeli yüklenirken arayüz `Dinliyorum` demek yerine hazırlanıyor/hazır durumunu gösterir.

## v4 - canlı konuşma kararlılık ve komut ayrımı
- Yazılı komut cevaplarının sohbette iki kez görünmesi düzeltildi: yazılı cevap artık Gemini Live'a tekrar ürettirilmiyor.
- `YouTube aç` ile `müzik aç` kesin olarak ayrıldı. Live tool çağrısından hemen önce son kullanıcı sözü flush edilerek yanlış `muzik_cal` seçimi düzeltiliyor.
- Gemini Live bir kez `1011 Internal error` verirse aynı program çalışması boyunca sonraki oturumlar doğrudan sade/stabil ayarla başlıyor; her uyanmada aynı bağlantı hatası tekrar denenmiyor.

## v5 — Canlı Aktivite / İşlem İzleme
- Yeni **Canlı Aktivite** sayfası: Jarvis'in gerçek arka plan adımlarını kullanıcı dilinde gösterir.
- Komut alındı, araç başladı, araç sonucu, yanıt iletildi ve hata/uyarı olayları zaman damgasıyla görünür.
- Araç sonucu dönmeden işlem **Tamamlandı** sayılmaz; başarısız sonuçlar kırmızı gösterilir.
- Gemini Live araç çağrıları (uygulama açma, müzik, görev, komut vb.) doğrudan aktivite akışına bağlandı.
- Self-Coder uygulama sonucu ve hata durumu aktivite ekranına bağlandı.
- Aktivite geçmişi sohbet/log geçmişini etkilemeden temizlenebilir.


## v6 — Tek ses + güvenli kapatma
- Canlı mod açıksa yazılı/web cevapları da seçili Gemini Live sesiyle (örn. Puck) okunur; Edge/Windows sesi yalnızca Live kullanılamadığında devreye girer.
- Yazılı cevap Live sesiyle okunurken Live transkripti ikinci sohbet balonu olarak gösterilmez.
- `Jarvis'i kapat` / `kendini kapat` / `uygulamayı kapat` yalnızca Jarvis uygulamasını kapatır; bilgisayar açık kalır.
- `bilgisayarı kapat` / `PC'yi kapat` ayrı sistem işlemi olarak kalır ve onay ister.
- Gemini Live'a `jarvis_kapat` adlı ayrı araç eklendi; modelin Jarvis kapatma isteğini PC kapatmaya çevirmesi engellendi.


## v7 — Self-Coder 2.0
- `Kendini incele ve geliştirme önerisi çıkar` komutu eklendi.
- Jarvis kaynak kodu değiştirmeden proje sağlık kontrolü + en fazla 5 geliştirme önerisi üretir.
- `1 numaralı geliştirmeyi uygula` ile seçilen öneri normal güvenli Self-Coder planına dönüşür.
- Kullanıcı onayı ve yüksek-risk onayı korunur.
- Test başarısızlığında önce rollback, sonra aynı dosyalarla sınırlı tek-seferlik otomatik düzeltme denemesi eklendi.
- İkinci test başarısızsa tam rollback yapılır; sonsuz kendi kendini değiştirme yoktur.

- `tests/test_router.py` regresyon testleri eklendi; Self-Coder artık compile kontrolüne ek olarak yerleşik unittest paketini de çalıştırır.

## v8 — Sade arayüz + Dosya Merkezi

- Ana gezinme sadeleştirildi: **Ana Sayfa, Sohbet, Dosyalar, Telefon, Ayarlar**.
- Ana sayfa kullanıcı dostu hale getirildi; aktif kullanıcı, hedefler, telefon, hafıza ve AI durumu tek bakışta görünür.
- Orta alana görsel JARVIS sahnesi ve **“Şu an ne yapıyor?”** göstergesi eklendi.
- Son aktiviteler ve öneriler ana ekranda özetleniyor; teknik detaylar Canlı Aktivite sayfasında kalıyor.
- **Dosyalar** bölümü ana özellik haline getirildi: kapsamlı analiz, Excel/Word/PDF çıktı, çeviri ve toplu analiz kısayolları.
- PDF/Word/Excel gibi format dönüştürme istekleri için `doc_convert` rotası eklendi.
- Kullanıcı analiz sonucunu açıkça Excel/Word/PDF isterse ikinci kez “çıktı al” demeden doğrudan o formatta kaydetme akışı eklendi.
- Ayarlar sadeleştirildi; günlük seçenekler önde, entegrasyon/model/sistem ayrıntıları **Gelişmiş** altında kaldı.
- Mevcut Kullanıcılar, Hedefler, Telefon, Hafıza, Self-Coder, Vision, Groq/Gemini/Ollama desteği kaldırılmadı.

## v9 — Denetim / Self-Coder kararlılık / güvenlik temizliği

- Self-Coder `.venv` ve diğer ağır klasörlere girmeden kaynak ağacı tarıyor.
- Self-Coder `compileall .` yerine yalnız proje `.py` kaynaklarını bytecode üretmeden derliyor.
- Self-Coder test komutları sabit güvenli listeye alındı; keyfî pytest/argüman çalıştırma kaldırıldı.
- Büyük dosya bağlamı görevle ilgili kod parçalarına ve toplam boyut sınırına alındı.
- Çekirdek, güvenlik, telefon ve Self-Coder dosyaları yüksek risk onayı istiyor.
- Başarılı Self-Coder sonucunun “geri al” kelimesi yüzünden hata sayılması düzeltildi.
- [v5.9 ile değişti] Self-Coder açık uygulama onayı ve başarılı testlerden sonra değişikliği yerelde korur; GitHub main yayını ayrıca `git yükle` komutuyla yapılır.
- GitHub açılış güncellemesi varsayılan kapalı; manüel güncelleme ayrı çalışıyor.
- Claude sağlayıcı kodu ve ayar arayüzü kaldırıldı; Gemini + Groq + Ollama kaldı.
- Kullanılmayan Three.js/world 3B dosyaları ve eski texture klasörü temizlendi.
- Ana canvas animasyonu yaklaşık 20 FPS'e çekildi.
- Komut günlükleri hassas veri redaction kullanıyor.
- Web ve telefon HTTP yanıtlarına ek güvenlik başlıkları eklendi.
- Telefon tokenı yeni kurulumlarda güçlendirildi ve yetkisiz deneme sınırı eklendi.
- Ayrıntılar: `DENETIM_RAPORU.md`.

## Telefon güvenliği ek sertleştirme (2026-10-05)
- `phone_token.txt` biçimi değiştirilmedi; mevcut mobil köprü uyumluluğu korunuyor. Dosya oluşturma/okuma/yenilemede izinler sıkılaştırılıyor; Windows üzerinde mevcut kullanıcı ACL uygulanıyor, diğer sistemlerde 0600 deneniyor.
- Telefon HTTP yanıtlarına Content-Security-Policy ve Permissions-Policy eklendi.
- Telefon HTTP sunucusu daemon worker, sınırlı istek kuyruğu ve adres yeniden kullanım ayarlarıyla çalışıyor; kapanış ve yoğun istek davranışı daha kontrollü.
- GitHub `main` tek ana geliştirme kaynağıdır. Açılışta yalnız güncelleme kontrolü yapılır; otomatik kurulum kapalıdır. [v5.9] Testten geçen yerel değişiklikler yalnız `git yükle` komutuyla main dalına yayınlanır.


## GitHub ana geliştirme akışı
- GitHub artık yedek değil, Ev/İş JARVIS kurulumlarının ortak ana sürüm hedefidir.
- Self-Coder değişikliği ancak güvenli testler geçtikten sonra `main` dalına tek commit olarak yayınlanır.
- Yayından önce dokunulan dosyalar için uzak sürüm çakışması kontrol edilir; farklıysa force-push yapılmaz.
- GitHub/ağ hatasında çalışan yerel değişiklik korunur ve güncelleyici tarafından ezilmez.
- Açılışta ana dal yalnız salt-okunur kontrol edilir; otomatik kurulum yoktur. `update_check=false` kontrolü de kapatır.
- GitHub tokenı URL veya komut satırına yazılmaz; mevcut korumalı token deposu kullanılır.

## v5 — Çalışma Modu
- Çalışma Modu tüm kullanıcılar için standart özellik oldu.
- Kaynaklar, ilerleme ve mod seçimi kullanıcı profiline özel tutulur; API key izolasyonu korunur.
- Kaynaktan Çalış, Öğretmen, Sınav, Matematik ve Uygulamalı modları eklendi.
- Kaynaklardan yalnız ilgili parçalar modele gönderilir; Kaynaktan Çalış modunda kaynak dışı bilgi uydurulmaz.
- Matematik cevaplarında sembol/işlem odaklı istem ve hafif yerel LaTeX-benzeri gösterim eklendi.

## v5.10
- Ayarlar > Bağlantılar bölümüne görünür **GitHub’a Yükle** düğmesi eklendi; açık onay + test + güvenli main yayını yapar.
- Uzak mesafe Hey Jarvis 4/10 ölçümüne göre dengeli eşik 0.18'e çekildi; art arda iki yakın skor doğrulaması eklendi.
- Dijital AGC hedefi 1250, üst sınırı x9 oldu; Windows mikrofon seviyesi değiştirilmez.

---

# Birleştirilmiş eski sürüm notları

## Kaynak: `DUZELTMELER_v5_1.md`

# JARVIS v5.1 düzeltmeleri

- Self-Coder başarısızlığında gerçek traceback `~/.jarvis/selfcoder_error.log` dosyasına yazılır.
- Arayüz aktivitesinde hata tipi ve kısa sebep gösterilir.
- Gelişim raporunda ERROR kayıtları artık toplam sorun sayısına dahil edilir.
- Groq varsayılanı `openai/gpt-oss-120b` oldu.
- Eski `llama-3.3-70b-versatile`, `llama-3.1-8b-instant` ve `qwen/qwen3.6-27b` ayarları otomatik olarak güncel varsayılana taşınır.
- Groq model seçenekleri güncellendi: `openai/gpt-oss-120b`, `openai/gpt-oss-20b`, `qwen/qwen3.8-27b`.

## Kaynak: `V5_2_DUZELTME.md`

# v5.2 — Aktif kullanıcı / Gemini / Self-Coder bağlantısı

- Bağlantılar > Gemini artık global legacy anahtara değil aktif kullanıcının anahtarına kaydeder.
- Ayarlar durum göstergesi aktif kullanıcının gerçek anahtarını gösterir.
- `llm_measure()` aktif kullanıcının istemcisini test eder.
- Her komut başında LLM kullanıcı bağlamı aktif profile eşitlenir.
- Groq/Ollama -> Gemini fallback kararı global anahtara değil aktif kullanıcının Gemini istemcisine bakar.
- Self-Coder yerel sağlık taramasını önce yapar; AI önerisi aşamasında aktif kullanıcının sağlayıcısını kullanır.

## Kaynak: `V5_3_SELF_CODER_GUVENLIK.md`

# JARVIS v5.3 — Self-Coder İncele/Uygula Güvenlik Kilidi

- **İncele** komutu salt-okunurdur; bekleyen uygulama planını iptal eder ve kaynak dosya parmak izini işlem öncesi/sonrası doğrular.
- `evet`, `tamam`, `devam` artık kaynak kod değişikliği onayı değildir. Normal/orta risk planlarda açıkça **uygula** gerekir.
- Yüksek riskli planlarda **yüksek riski onaylıyorum** ifadesi gerekir.
- Tek Self-Coder planı en fazla 6 farklı kaynak dosyasına dokunabilir; daha büyük işler parçalanır.
- Arayüzde öneri düğmesi **Planı hazırla** olarak netleştirildi.
- Başlangıçta uzaktan gelen toplu değişiklik bildirimi artık **GitHub güncellemesi uygulandı** diye görünür; Self-Coder değişikliğiyle karışmaz.
- Self-Coder değişiklikleri uygulanmadan önce yedek/rollback, ardından test ve başarılıysa GitHub akışı korunur.

## Kaynak: `DUZELTMELER_v5_4.md`

# v5.4 — Merkezi kullanıcı/API bağlamı

- Aktif kullanıcı/API çözümleme için `llm.set_user_context()` eklendi.
- UI durum bilgisi `llm.key_state()` üzerinden aynı kaynağa bağlandı.
- Sistem Taraması aktif profil slug bilgisini AI kontrol iş parçacığına açıkça geçiriyor.
- Self-Coder/sohbet/çalışma akışlarının kullandığı LLM bağlamı aynı merkezi girişten ayarlanıyor.
- Kullanıcılar arasında Gemini anahtarı fallback edilmez.
- Amaç: Ayarlar “Aktif” derken Sistem Taraması “anahtar yok” deme tutarsızlığını kaldırmak.

## Kaynak: `HATA_DUZELTMELERI_v5.6.md`

# JARVIS v5.6 — Hata temizleme

- Mikrofonun geçici `Stream is stopped` / `Stream is not active` PortAudio durumu artık kalıcı mikrofon hatası sayılmıyor. Dinleme döngüsü kısa bekleyip yeni stream ile devam eder.
- `api_key_save`: anahtar başarıyla kaydedildikten sonraki model ölçümü hata verirse API endpoint'i çökmez; UI gerçek model hatasını sonuç olarak gösterir.
- `snapshot`: alt modüllerden biri geçici hata verirse bütün UI yenilemesi düşmez. Güvenli asgari snapshot döndürülür ve uyarı loglanır.
- Eski Gelişim Raporu kayıtları silinmez. Düzeltmenin doğrulaması, yeni kullanım sırasında aynı hata sayaçlarının artmamasıyla yapılmalıdır.

## Kaynak: `DEGISIKLIKLER_v5.7.md`

# v5.7 — Tek Ana Sürüm + Kullanıcı API İzolasyonu

- GitHub `main` Ev/İş için tek ana kod kaynağı olarak belgelendi.
- Açılışta yalnız güncelleme kontrolü var; otomatik kurulum yok.
- GitHub'a gönderilmemiş Self-Coder yerel değişikliği varsa updater kurulumu reddeder.
- README / SELF_CODER.md / GITHUB_AKISI.md gerçek kod davranışıyla eşitlendi.
- Global Gemini durum fallback'i UI'dan kaldırıldı; aktif profil anahtarı gösterilir.
- Başlangıçta ortak Gemini anahtarı isteme kaldırıldı; anahtar profil Ayarları'ndan tanımlanır.
- Groq da kullanıcıya özel anahtar deposuna alındı; kullanıcılar arası fallback yok.
- Klasik arayüzdeki Gemini anahtar göstergesi/kaydı da profil bazlı hale getirildi.
- Mimari regresyon testleri eklendi.

## Kaynak: `DUZELTMELER_v5.8.md`

# JARVIS v5.8 — İnceleme, Hatırlatma ve Hey Jarvis

- Self-Coder büyük dosyalarda gördüğü kesitleri artık dosyanın tamamı sanamaz. `main.py`/`web.py` için "dosya kesilmiş" yanlış alarmı, tam Python derleme kontrolü başarılıysa elenir.
- Zamana bağlı hatırlatmalar kalıcı kullanıcı kuralı olarak kaydedilmez. Canlı mod, gün/saat içeren hatırlatma isteğinde `hatirlatma_ekle` aracını kullanmak zorundadır.
- Saat verilmeyen tüm-gün hatırlatmaları ilgili gün 09:00'da (Jarvis daha geç açıldıysa o gün ilk kontrolde) kendiliğinden bildirilir.
- Eski sürümden kalmış zamana bağlı "hatırlatacağım" kuralları kullanıcı verisinden otomatik silinmez, ancak konuşma promptuna sokulmaz.
- Hey Jarvis orta hassasiyet eşiği 0.35'ten 0.28'e indirildi.
- Jarvis artık Windows ses karıştırıcısında kendi uygulama sesini zorla %100 yapmaz; Windows ses/mikrofon kaydırıcılarına dokunmaz.
- Canlı mikrofon dijital AGC üst sınırı x12'den x8'e indirildi; bu yalnız Jarvis içinde işlenen sese uygulanır, Windows mikrofon seviyesini değiştirmez.

## Kaynak: `DEGISIKLIKLER_v5.9.md`

# JARVIS v5.9

- Ev/İş ayrımı kaldırıldı: hangi PC'de yerel değişiklik yapılırsa yapılsın aynı GitHub `main` hedeflenir.
- Self-Coder testten geçen değişikliği artık otomatik push etmez; yerelde korur.
- `git yükle`, `GitHub'a gönder` veya `GitHub'a yükle` açık komutu testleri yeniden çalıştırıp yerel kaynak farklarını `main` dalına yollar.
- Uzak `main` bu PC'nin kayıtlı taban sürümünden ilerideyse yayın engellenir; önce kontrollü güncelleme gerekir. Force-push yoktur.
- API anahtarları, kullanıcı verisi, `.venv`, cache ve benzeri alanlar yayına dahil edilmez.
- Hey Jarvis orta eşik 0.28 -> 0.22; 4/5 hassasiyet seviyeleri de orantılı iyileştirildi.
- Dijital AGC hedefi 900 -> 1100; Windows mikrofon seviyesine yine dokunulmaz.
- Güncelleyici artık yalnız Self-Coder kaydına değil, kayıtlı GitHub tabanına göre tüm yerel kaynak farklarına bakar; yayımlanmamış manuel/ZIP değişikliğinin üzerine yazmaz.

## Kaynak: `DEGISIKLIKLER_v5.10.md`

# JARVIS v5.10

- Ayarlar > Bağlantılar > GitHub bölümüne **GitHub’a Yükle** düğmesi eklendi.
- Düğme açık onay ister, regresyon testlerini çalıştırır ve yalnız güvenli fast-forward koşullarında `main` dalına yayınlar. Force-push yoktur.
- Self-Coder ekranındaki eski “testten sonra otomatik GitHub’a gönderilir” metni düzeltildi; yayın yalnız açık `git yükle` komutu veya düğmeyle yapılır.
- Uzak mesafe Hey Jarvis testi 4/10 olduğu için dengeli eşik 0.22 -> 0.18 yapıldı.
- Uzak/kısık ses için dijital AGC hedefi 1100 -> 1250, üst sınır x8 -> x9 oldu; Windows mikrofon seviyesi yine değiştirilmez.
- Tek düşük skorla yanlış uyanmayı artırmamak için, doğrudan eşiğin altında kalan seslerde art arda iki yakın skor doğrulaması eklendi.

## Kaynak: `DEGISIKLIKLER_v5.11.md`

# JARVIS v5.11 — Cinematic Command Center

- Ana sayfa, onaylanan açık/sıcak sinematik tasarıma göre yeniden düzenlendi.
- Sol sütun: kullanıcı, Gemini/Groq/Ollama, mikrofon/GitHub/telefon/PC ve CPU/RAM/Disk durumu.
- Merkez: mevcut holografik dünya, karşılama, hızlı eylemler, komut çubuğu ve Hey Jarvis durumu.
- Sağ sütun: canlı aktivite, yaklaşan hatırlatmalar ve kullanıcı onaylı GitHub'a Yükle düğmesi.
- Saat alanına gerçek snapshot hava durumu (sıcaklık, şehir, açıklama) eklendi.
- Arka plan gece görünümünden daha aydınlık gün batımı/akşam tonlarına taşındı.
- Üst menü sadeleştirildi; Uygulamalar ve Self-Coder sayfaları kaldırılmadı, yalnız ana menüden çıkarıldı ve mevcut giriş noktalarından erişilebilir.
- GitHub durumu snapshot'a yerel/ucuz biçimde eklendi; bu kontrol ağ çağrısı yapmaz.
- Diğer sayfaların çalışma mantığı değiştirilmedi.


## Çalışma Modu — Son 3 Yıl Çıkmış Soru Odağı
- Kitap/kaynak ile çıkmış soru kaynakları ayrıldı.
- Çıkmış sorular yıl etiketiyle ekleniyor; en yeni 3 yıl otomatik önceliklendiriliyor.
- Konu ve soru tarzı önceliği %70 son 3 yıl çıkmış soru / %30 kitap-kaynak olarak ayarlandı.
- Öğretim bilgisinde kitap/kaynaklar birincil; çıkmış sorular sınav eğilimi ve soru tarzı sinyali.
- Resmi cevap anahtarı yoksa JARVIS bir cevabı resmi cevap gibi göstermiyor.

## 2026-10-05 — Son 3 yıl analiz + küçük mikrofon düzeltmesi
- Çalışma Modu: son 3 yıl için en çok çıkan konu, yükselen konu ve soru tipi dağılımı analizi eklendi.
- Analiz profil bazlı önbelleğe alınır; çıkmış soru eklenince/silinince geçersiz olur ve ilk çalışmada otomatik yenilenir.
- Analiz sonucu çalışma planı ve sınav soru seçimine öncelik sinyali olarak eklenir; kitap/kaynak öğretim temeli olmaya devam eder.
- Küçük masaüstü JARVIS mikrofon düğmesinin DPI altında tıklama alanı genişletildi.
- Mikrofon kapatıldığında yalnız bayrak değiştirmek yerine açık Gemini Live dinleme oturumu da kapatılır; web, küçük pencere ve sistem tepsisi aynı merkezi mikrofon anahtarını kullanır.

## 2026-10-05 — Küçük JARVIS mikrofon anahtarı: gerçek donanım kapatma
- Küçük JARVIS durumları referans tasarıma göre korunur: Hazır (altın), Dinliyor (yeşil), Düşünüyor (turuncu), Konuşuyor (mavi), Mikrofon kapalı (gri), Uykuda (mor).
- Sağdaki mikrofon düğmesi artık tek ana mikrofon anahtarıdır; şeridin gövdesine tıklamak kapalı mikrofonu yeniden açmaz.
- Mikrofon kapatılınca aktif tek-seferlik dinlemeler `mic_cancel` ile hemen kesilir.
- Gemini Live açık oturumu kapatılır ve Live mikrofon döngüsü PortAudio InputStream'i gerçekten serbest bırakır; yalnızca ses örneklerini görmezden gelmez.
- Mikrofon kapalıyken `listen` olayı Live oturumunu yeniden açamaz.
- Acil durdur da aynı merkezi mikrofon kapatma yolunu kullanır.
- Mikrofon tekrar açılınca iptal kapısı temizlenir ve dinleme normal şekilde yeniden başlayabilir.

## 2026-10-06 — Çalışma Modu sınav odaklı son düzenleme
- GitHub yönleri ayrıldı: `GitHub'a Yükle ↑` ve `GitHub'dan Al ↓`. Al işlemi yerel kaynak değişikliği varsa dosyaların üzerine yazmaz.
- GitHub senkron doğrulaması SHA metni karşılaştırmak yerine GitHub commit grafiğini (compare API) kullanır; `remote_ahead / local_changes / diverged` ayrımı gerçek commit ilişkisine göre yapılır.
- Çıkmış sorular artık yıl yanında isteğe bağlı `Dönem` ve `Oturum` etiketi taşır. Soru kimliği kaynak belge ID'sini de içerdiği için aynı yıl/aynı soru numarası çakışmaz.
- Çalışma ana ekranına sınava kalan gün, hazırlık yüzdesi, bugünkü hedef ve son 3 yıl kapsaması eklendi; `Bugünkü Çalışmayı Başlat` en öncelikli zayıf konuya gider.
- `Yanlışlarım` yanlış defteri eklendi. Yanlış sorular ertesi gün, ilk doğru tekrardan sonra 3 gün sonra yeniden gelir; iki doğru tekrardan sonra öğrenilmiş sayılır.
- `Deneme` modu eklendi: 10 soru, 20 soru veya tam deneme. Sorular son 3 yılın gerçek havuzundan seçilir; sonuçta konu bazlı başarı gösterilir.
- Yeni eklenen PDF kitaplarda sayfa sınırları korunur; kaynak parçaları ve cevap kaynaklarında `Sayfa N` bilgisi gösterilebilir.
- Konu anlatımında `Konu Kilidi` var: kullanıcı açıkça konu değiştirmeden JARVIS başka derse/konuya geçmez. Zorunlu ön bilgi en fazla birkaç cümle verilir ve hemen ana konuya dönülür.
