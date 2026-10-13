# Bekleyen doğrulamalar

## Komut ve masaüstü entegrasyonu — 11 Ekim 2026

- PC ölçümü: tek + basışı sonrası `CalculatorExpression.name` boş `İfade değeri` → `İfade değeri 12 +`, offscreen true → false; sonuç `Ekran değeri 12` aynı. Boş ifade salt okunur gözleme dahil edildi, operatör planı ifade değişimiyle doğrulamaya yönlendirildi. Gerçek PC'de tam 12 + 7 = 19 görevi hâlâ bekliyor.

- PC görüntüsündeki `pc görev iptal` söylenişi yalnız `pc görevi` önekini tanıyan motora ulaşmıyordu; her iki önek ve son noktalama kabul edilir, açık masaüstü komutları diğer yorumlayıcılardan önce yönlendirilir. Gerçek PC'de eski görev iptali ve yeni 12 + 7 görevi bekliyor.

- PC ölçümü: açık Hesap Makinesi listede ve başlığıyla UIA okuması başarılı (CalculatorApp PID, 52 kontrol). `calc`/`calculator` hedefleri UWP süreç adı nedeniyle seçilemiyordu. Ad eşleştirme ve UIA ile açılış doğrulama düzeltildi; gerçek Windows'ta yeni sesli/yazılı görevle 12 + 7 = 19 sonucu ayrıca doğrulanmalı. İki `gui.py` ana–alt süreç zinciri, tek Jarvis örneği olarak doğrulandı.

- PC denemesinde Hesap Makinesi hedefi desteklenmeyen uygulama kimliğiyle durdu; gerçek UIA süreç kimliği, Calculator adı ve yalnız doğrulanmış Calculator içeren Windows host desteği eklendi. Gerçek Windows'ta işlem/sonuç tekrar denenmeli.
- Ekrandaki `.gitattributes test sırasında değişmiş` hatasının hangi dış işlemden kaynaklandığı doğrulanmadı. ZIP filtresinin bu dosyayı düşürmesi düzeltildi; eşzamanlı kaynak değişikliğinde duruş korunur. Güncelleme sırasında VS Code/diğer ajanların aynı kaynakları yazmadığı ortamda tekrar denenmeli.
- Güncel GitHub koduna uygulama sonuç doğrulaması, konuşma bağlamı, şifreli taslak testleri ve kalıcı masaüstü görevleri birleştirildi. Otomatik model/OS taklitleriyle test edilir; gerçek Windows UI Automation ve canlı model ayrıca denenmelidir.
- PC denemesi: Hesap Makinesi'nde `12 ile 7 topla`, adsız Not Defteri'nde metin geri okuma, değişen pencere/onay iptali ve şifreli geliştirme kilidi. Ayrıntılar: [MASAUSTU_GOREVLERI_20261011.md](MASAUSTU_GOREVLERI_20261011.md).
- Yerel masaüstü uygulama desteği şimdilik Hesap Makinesi ve düz metin Not Defteri ile sınırlıdır; diğer uygulamalar ve üçüncü taraf proje klasörlerinde geliştirme açık iştir.

Güncel paket: 7 Ekim 2026. Önceki hata kaydı, bağımlılık kilidi, dizin düzenleme, erişim anahtarı ve hava durumu bakım maddeleri tamamlandı; açık iş listesinden çıkarıldı.

- Gerçek Windows bilgisayarında mikrofon kapatma, Hey Jarvis ve ücretli sağlayıcı seçimi sonrası dinleme geçişi.
- Gerçek Windows üzerinde pencere öne getirme, küçültme/büyütme ve hedefli klavye işlemleri.
- Kullanıcının seçtiği model ve kendi API anahtarıyla OpenAI/Claude gerçek bağlantısı; ücretli deneme otomatik yapılmaz.
- Gerçek telefonda mikrofon/Siri denemesi ve eski Siri kestirmesinin POST/X-Token akışına uyarlanması.

Kurulum ve kapsam: [README](../README.md), [sesli işlemler](SESLI_ISLEMLER.md), [sağlayıcılar](YAPAY_ZEKA_SAGLAYICILARI.md).

- Şifreli geliştirme modunda kullanıcının kendi modeliyle gerçek kod/tasarım isteği; kota, yanıt kalitesi ve Windows üzerinde test/geri alma akışı.
- Gerçek mikrofonla geliştirme takip isteği ve telefondan görsel referans gönderimi.

- Smart Router: kullanıcının ücretsiz Gemini/Groq hesapları ve OpenRouter/Ollama ile gerçek kota/fallback denemesi.
- Playwright Chromium: bu ortamda indirme başarısız; gerçek Windows tarayıcıda gezinme/form/onay/sonuç kontrolü.

Smart Router, görev yürütücüsü, tarayıcı kodu ve PC/ses tanılama eklendi; otomatik testler donanım veya canlı servis denemesi yerine geçmez. [Kullanım](SMART_ROUTER_AJANLAR.md).

## Geliştirme ortamı kurulumu (11 Ekim 2026)

Ayrıntılar: [GELISTIRME_ORTAMI.md](GELISTIRME_ORTAMI.md). Yukarıdaki maddeler aynen korunmuştur.

**Tamamlananlar (bu bilgisayarda)**
- Yerel Git deposu ve ilk commit (`ilk-kurulum`, `869b81c`, 422 dosya). GitHub bağlantısı kuruldu; geliştirme düzeni PR #47 ile `main`'e birleşti (`28ec38e`). Yerel ses süzgeci (#48) ve ipucu/hız ayarı (#49) da birleşti; gerçek PC denemeleri açık.
- `.gitignore` genişletildi (hafıza veritabanları, model ve imzalama anahtarı desenleri); kaynakta anahtar/veritabanı/model bulunmadı.
- `run_tests.bat`: testlerden sonra güvenli başlangıç kontrolü. Tüm test grupları ve başlangıç kontrolü geçti (çıkış 0).
- Playwright 1.58.0 ve Chromium kurulu; headless Chromium açılışı denendi.
- Headroom 0.40.0 (`uv tool`, `.venv`'den ayrı) kuruldu; `/health` sağlıklı; gerçek trafik de doğrulandı (Hamdi'nin bildirimi: dashboard 67 istek, %24 toplam token azaltma).
- Task Observer 3.6.0 kuruldu; yeni oturumda SessionStart kancası çalıştı, skill çağrıldı, gözlem kaydı betikle oluştu.
- `jarvis-kural-denetcisi` ajanı ve `tools/claude/kur-ajanlar.ps1` (PowerShell 5.1'de eşit/farklı/`-WhatIf`/yanlış klasör senaryoları denendi).

**Doğrulanmamış noktalar**
- Task Observer: ilk haftalık inceleme yapılmadı; `0001-kurulum-dogrulama` kaydı açık. Birkaç gerçek oturum sonra `observation-log/` altında gerçek kayıt oluştuğu doğrulanmalı.
- Denetçi ajanı: gerçek PR öncesi (#47-#49) çalıştırıldı ve `dosya:satır` ayrıntılı rapor verdi. Headroom açıkken eksik rapor sorunu aşağıdaki maddede.
- Playwright Chromium: yukarıdaki "indirme başarısız" notu o ortama aitti; bu bilgisayarda kurulu ve açılıyor, ama gerçek gezinme/form/onay akışı denenmedi.
- `kur-ajanlar.ps1` bu bilgisayarda Windows PowerShell 5.1 ve PowerShell 7.6.6 ile denendi (normal, CRLF'li, BOM'lu, uzun başlıklı, bozuk başlıklı dosya, `-WhatIf`, tekrar çalıştırma; sonuçlar aynı). Ikinci bilgisayar denenmedi. Dosyada "internetten indirilmiş" işareti varsa `-ExecutionPolicy Bypass` olmadan çalıştırmak engellenir; belgedeki komut Bypass içerir.
- Jarvis'in kendi yayını ve güncelleyicisi `.ps1` uzantısını kabul etmiyor; betik yalnız Git ile taşınır.
- Headroom açıkken `jarvis-kural-denetcisi` raporunda eksik bölümler ve `<<ccr:...>>` yer tutucuları görüldü (11 Ekim 2026). Sebebi henüz belirlenmedi; Headroom ile bağlantısı doğrulanmadı. Denetçi raporu eksik gelirse tekrar tekrar çalıştırılmaz, eksiklik bildirilir.

**Diğer bilgisayarda sıradaki adım**
1. Depoyu GitHub'dan al (`hamdkose-ctrl/Jarvis`, `main`; ya da `git bundle`/klasör kopyası) ve `kurulum.bat` çalıştır.
2. `tools\claude\kur-ajanlar.ps1` ile ajanı kur; `claude plugin list` ile eklentilere bak, eksikleri ekle.
3. `run_tests.bat .venv\Scripts\python.exe` ile doğrula.
4. Tamamlandı: yerel geçmişi GitHub geçmişine bağlama geçmiş korunarak PR #47 ile yapıldı (force push ve yeni `main` yok). Yerel `ilk-kurulum` ve `gelistirme-duzeni` dalları eski köktür, silinmedi.

## Masaüstü görevleri, Windows komutları ve dosya işlemleri — 11 Ekim 2026

- Dört yığılı dal `main`'e birleşmedi (sıra: `codex/desktop-whitespace-20261011` → `desktop-goal-guard` → `desktop-apps` → `dosya-islemleri`); PR'ı Hamdi açar. Arayüz (`webui/`) işi bitince hepsi birlikte birleştirilecek. O zamana kadar "Yedekle ve GitHub'dan Al" kullanılmaz (çalışan kodu `main` sürümüyle değiştirir).
- Açık hata: Canlı sesle "PC ayarlarını aç" / "Windows ayarları aç" Jarvis'in kendi ayar sayfasını açıyordu. Canlı model talimatına "PC/Windows sözcüğünü silmeden ilet" kuralı eklendi (f5ccae8) ama yeniden başlatıp denenmedi. Hâlâ olursa etkinlik kartındaki "Komut motoru isteği işliyor" cümlesi gerekir; komut metni günlüğe bilerek yazılmıyor (gizlilik kararı Hamdi'de).
- Jarvis arayüzünden sesle uçtan uca denenmedi: uygulama izni sorusu (evet/hayır), "PC not defteri", "PC dosyaları", dosya taşı/yeniden adlandır/oluştur/geri al.
- Windows Ayarlar'ın 16 sayfasından yalnız Wi-Fi ve Ses gerçek PC'de doğrulandı. Dosya Gezgini masaüstü görevi denenmedi. Paint'te yalnız araç seçimi (Çizgi kalemi, Dikdörtgen) denendi; ikinci bir kullanıcıyla izin ayrımı denenmedi.
- Sembolik bağ elemesi (`file_ops`) için test yok (Windows'ta oluşturmak yönetici izni isteyebilir).
- Bilerek yapılmadı: fare/koordinat kontrolü ve tuvale çizim (UIA yetmeyen somut bir iş çıkarsa dar bir araç tasarlanır); Not Defteri'nde kaydet penceresi (metin dosyası oluşturma komutu yerine geçer).
- Kota: uzun Claude oturumları her mesajda büyük bağlam yeniden gönderdiği için kotayı hızlı harcar; yeni iş için yeni oturum açılması önerildi.


## Hologram entegrasyonu — 13 Ekim 2026

- Tamamlandı: onaylanan yakın kadraj doğrudan ana ekrana alındı; `S.orb` durumları, silüet tıklamasıyla mevcut mikrofon eylemi, üç renk/iki arka plan, yeniden oynatma ve sayfa kapanışında kaynak temizliği bağlandı. Sunucu, model havuzu, ses motoru ve Android değiştirilmedi.
- Doğrulama: Node davranış testleri ve shader derleme/çizim kontrolleri; tam paket doğrulamasının sonucu teslim rehberindedir.
- Gerçek PC'de bekleyen: Edge/Chrome ile açılış ve menüden ana ekrana dönüş; mikrofon/yerel Whisper ve TTS sırasında gerçek DİNLİYOR/DÜŞÜNÜYOR/KONUŞUYOR durumları; 1080p/4K akıcılık; WebGL bağlamının kaybolup geri gelmesi.
- Konuşma görseli gerçek duruma bağlıdır; sesin gerçek genliği henüz çizime aktarılmaz. GitHub yayını/PR bu işte yapılmadı.


## Ortak görev çekirdeği — 13 Ekim 2026

- Tamamlandı: aynı görev kimliğinde güvenli sürdürme, görev iptal/geçmişi, rapor bütünlüğü ve kullanıcıya özel görev bağlamı. Ana plan: JARVIS_ANA_PLAN.md.
- Bekliyor: canlı Windows tam doğrulaması ve gerçek model/tarayıcı işleriyle kesinti-devam denemesi.
- Bekliyor: resmi çok servisli bağlantılar (Gmail gönderim, Telegram, WhatsApp, YouTube/Instagram yayın/takip), üretim zinciri ve zamanlanmış arka plan yürütücüsü. Bu pakette bağlanmış sayılmazlar.
- Bilinen sınır: eski görev dosyalarının digest'i yoktur; varlık kontrolü içerik bütünlüğü kanıtı değildir. Kooperatif iptal dış serviste başlamış işlemi geri alamaz.

## Sonuç doğrulama teslimi — 13 Ekim 2026
- Tamamlandı: araştırma/rapor/kod/tarayıcı için ortak sonuç kanıtları, onay dönüşü ve devam kontrolü.
- Açık: gerçek Windows, model ve hesap denemeleri; içerik doğruluğu ve yayının platformdaki son durumunu kontrol eden servis bağlantıları.
- Eski kanıtsız görevler yeni doğrulayıcıda durabilir; otomatik dış işlem tekrarı yerine sonucu incele veya yeni görev oluştur.

## Araç girdisi ve çalışma kaydı — 13 Ekim 2026
- Tamamlandı: beş görev worker'ında alan/tür/boyut doğrulaması, çalışma bağlamından kimlik/risk kaydı ve dış etkisi belirsiz hata sınıfı. 58 odaklı test, 20 Node grubu ve 6 smoke kontrolü geçti.
- Bekliyor: genel PC araçlarının aynı sözleşmeye bağlanması, resmi servis uyarlayıcıları ve canlı Windows/hesap doğrulaması. `task_tools` yeni izin vermez ve framework kurulumu yapmaz.

## Hesap uyarlayıcıları başlangıcı — 13 Ekim 2026
- Tamamlandı: Gmail `list_unread` mevcut salt-okuma OAuth üzerinden ortak görev worker'ına bağlandı. Mail başlıkları → rapor → doğrulama zinciri, kullanıcı ayrımı, gizlilik engeli, eksik izin ve değişmiş kayıt test edildi. `görev mail oku` ve destek kataloğu komutları eklendi.
- Kontroller: 69 odaklı test geçti; router/ajan smoke geçti. Genel 944 testte önceki 8 Windows ayar penceresi başarısızlığı ve 2 atlanan test var.
- Bekliyor: gerçek Gmail OAuth/API denemesi; mesaj gövdesi/ek, cevap taslağı ve açık yetkili gönderim; Telegram, resmi WhatsApp, YouTube/Instagram uyarlayıcıları; sürekli takip. Mevcut WhatsApp yolu ayrı kalır.

## Gmail metin ve taslak aşaması — 13 Ekim 2026
- Tamamlandı: seçilen mailin gövdesini sınırlı MIME çözümlemeyle okumak; doğrulanmış listeden mail seçmek; mail → yerel Markdown cevap dosyası → doğrulama. Doğrudan ilk mail ve kimlikle seçim komutları eklendi. Önceki liste kayıtları aynı gösterim/özetle kontrol edilir.
- 80 odaklı test geçti. Router/ajan smoke geçti (OS/model taklitleri). Canlı Gmail, model cevap kalitesi ve Windows denemeleri yapılmadı.
- Bekliyor: ek okuma, Gmail hesabında taslak/gönderim, servis izin kaydı, diğer servisler ve takip. Gövde ve taslak kullanıcıya özel yerel kayıtlardır; seçili bulut model taslak üretirken mevcut LLM yolu geçerlidir.

- Gmail taslak son kod tam test sonucu: 955 test, bilinen 8 Windows başarısızlığı ve 2 atlanan test.

## Birleşik son paket — 13 Ekim 2026
- Uygulandı: ortak outbox/servis-hedef yetkileri, tek içerik onayı, gönderim öncesi kalıcı kayıt, accepted sonuçtan kesinti kurtarma; beş servis yazma uyarlayıcısı ve Gmail/Telegram/YouTube/Instagram okuma yolları.
- Uygulandı: engine'e bağlı kalıcı tek sefer/tekrar okuma-rapor-medya kuyruğu, lease/heartbeat, sabit görev kimliği, kullanıcıya bildirim ve iptal; yerel görsel/ses → video ve medya → YouTube kaynak bağımlılığı.
- Kontroller: 105 odaklı/güvenlik testi; 20 Node grubu ve 6 smoke kontrolü geçti. Gerçek FFmpeg/FFprobe ile video üretildi. API/model/OS sınırlarında taklit kullanıldı. Genel testlerde önceki 8 Windows ayar penceresi başarısızlığı, 2 atlanan test kaldı; yeni başarısızlık yok.
- Gerçek PC'de: hesap bağlantıları, ayrı Google yazma kapsamları, Meta Business/profesyonel hesap izinleri, Telegram bot/chat yapılandırması, FFmpeg kurulumu ve kontrollü canlı gönderim/yayın kabulü yapılmalı. WhatsApp maliyet yetkisi otomatik açılmaz.
- Açık ürün kapsamı: WhatsApp geçmiş/webhook/teslim, Instagram Reels/yorum, YouTube yorum takibi, tam bot güncelleme tüketimi, gelişmiş üretim stüdyosu ve genel uzman paralelliği. Bu paket bunları tamamlandı diye sunmaz. Rehber: JARVIS_BIRLESIK_KULLANIM.md.


## Son genişleme — 13 Ekim 2026

Mesaj kutusu ve teslim durumu, kendi içeriklerine yorum okuma/yanıtlama, aynı Instagram Reels konteynerini takip etme, güvenli rollerin paralel çalışması ve yerel sahneli video üretimi uygulandı. WhatsApp yalnız etkinleştirildikten sonra gelen webhook olaylarını saklar; geçmiş sohbeti API üzerinden çekmez. Ayrıntılar: [Mesaj, yorum ve stüdyo](MESAJ_YORUM_STUDYO.md).

Canlı hesap/OAuth ve dış HTTPS webhook kurulumu, gerçek Windows/mikrofon kabul testi, kullanıcının Piper modeli veya Windows SAPI ile ses kalitesi hâlâ doğrulanmalıdır. Video stüdyosu sahne, görsel, altyazı ve ses montajıdır; fotogerçekçi üretken video modeli içermez. Eski açık iş maddeleri bu yeni kapsamla birlikte okunmalıdır.

## Güncellemede eski GitHub sürümünü reddetme — 13 Ekim 2026

Güncelleme kontrolü, kaynak doğrulama ve yedekleyerek kurma yolları kayıtlı yerel commit'in gerisindeki GitHub commit'ini ayırt eder. Eski sürüm yeni güncelleme diye sunulmaz; yedek seçeneği geriye kurma engelini aşamaz. Engellenen işlem kaynakları ve kayıtlı commit'i değiştirmez.

Bu koruma kayıtlı commit ilişkisine dayanır; ZIP'in yükleme tarihi veya dosya tarihleri sürüm kanıtı değildir. Taban commit bilinmiyorsa ya da yerel kaynaklar yayınlanmadıysa GitHub'ın güncel olduğu varsayılmaz. Normal güncellemenin yerel değişiklik engeli korunur; ayrışmış sürümü açıkça yedekleyerek alma mevcut davranıştır. Önce güncel yerel kaynakları doğrulayarak eşitlemek gerekir. Canlı Windows ve hesap kontrolleri açık kalır.

## Yerel servis kurulum kontrolü — son sürüm

`hesap durumu`, `hesap kurulumu kontrol` ve `servis durumu` mevcut kullanıcı için OAuth dosyaları, servis yapılandırmasının gerekli alanları, WhatsApp webhook/maliyet yetkisi, Telegram güncelleme tüketimi ve FFmpeg/FFprobe/Piper/SAPI önkoşullarını gösterir. Kontrol ağ çağrısı, OAuth yenileme, giriş penceresi veya ayar yazımı yapmaz; sır ve dosya yolu göstermez. Dosyanın/programın bulunması canlı bağlantı, geçerli izin veya çalışma testi değildir. Kullanıcı ve istek sahibi eşleşmelidir. Gerçek Windows/mikrofon/hesap, HTTPS webhook ve ses kalitesi kabul testleri hâlâ açıktır.
