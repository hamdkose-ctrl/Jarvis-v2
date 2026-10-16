# Güncel açık işler — 14 Ekim 2026

14 Ekim kullanıcı PC sonuçları: 1045 test ve tüm JS/smoke grupları ile başlangıç bağımlılık kontrolü geçti (9 test atlandı). Kamera açıldı; Hesap Makinesi 12 + 7 = 19 ve SAPI WAV üretimi doğrulandı. Gmail canlı okunmamış liste ve boş ek listesi döndü; gerçek ek içeriği okumaya uygun mail yoktu. Ekran paylaşımı yazım yönlendirmesi ve mail/kuyruk metinleri düzeltildi. Hesap Makinesi yavaşlığı için tur süresi eklenmiştir; hız iyileşmesi gerçek PC'de henüz ölçülmedi. Bu PC'de FFmpeg/FFprobe bulunamadı. Kuyruk kaydedildi ve bekliyor görüldü; gerçekten çalıştığı/yeniden başlatma/iptal kabulü henüz kanıtlanmadı. Mail/hesap kişisel içeriği depoya eklenmez.

Altyapı tamamlama kodu: ortak PC işlem sözleşmesi, kesin kayıtla hafıza düzeltme/unutma ve sabit uzman üretim akışları eklendi. PC kabul betiği otomatik kontrolleri ve elle bekleyen donanım/hesap kontrollerini ayrı kaydeder. Kapsam ve komutlar: [V2 tamamlama ve PC kabulü](V2_TAMAMLAMA_VE_PC_KABUL.md). Gerçek Windows, bağlantılar ve cihaz kalitesi bu kod değişikliğiyle tamamlanmış sayılmaz.

Yeni paketin doğrulaması: 1060 Python testi (2 atlanan), 22 JavaScript grubu ve 6 smoke grubu. OS/model/hesap sınırlarında taklit kullanılır; canlı kabul ayrı kalır.

Esas sürüm: son ZIP ile doğrulanmış Jarvis-v2. Aşağıdaki tarihli kayıtlar geçmiş aşamalardır; güncel durum bu listedir.

- Gerçek Windows: mikrofon/Hey Jarvis, TTS, ekran/kamera, pencere işlemleri, masaüstü izinleri ve iptal; hologram akıcılığı.
- Video araçları: önceki ortamda H.264/FFprobe kabulü bildirilmişti; son PC raporunda FFmpeg/FFprobe eksik. Bu PC'de kurulum ve gerçek üretim kontrolü bekliyor. Ses ve hesap kontrolleri ayrı kalır.
- Anlatım: yerel anlatımı kontrol et; Windows SAPI veya kullanıcının mevcut Piper modeliyle dil/kalite.
- Hesaplar: mevcut kullanıcı Gmail/YouTube OAuth kapsamları; Telegram bot/sohbet, Meta Business/profesyonel hesap ve HTTPS webhook. Gerçek izin/okuma/gönderim/yayın kabulü.
- Yeni özel depoya kullanıcı GitHub anahtarının erişimi ve kaynak doğrulaması. Eski deponun sürüm kaydı taşınmaz.
- Telefon/Android/iOS: cihaz ve APK kabul testi ayrı çalışma; bu aşamada Android kaynakları değiştirilmedi.
- Açık ürün sınırları: geriye dönük WhatsApp sohbet çekme, taranmış/şifreli ve eski ikili Office Gmail ekleri, fotogerçekçi üretken video ve sınırsız genel masaüstü geliştirme mevcut kapsamda tamamlanmış değildir.

Kodda uygulanmış: kalıcı görev/kanıt kurtarma, servis outbox/izin ve zamanlama, mesaj/teslim, kendi içeriklerine yorum, Reels, güvenli paralel roller, yerel montaj, kurulum kontrolleri, eski commit'e dönüş engeli ve Windows symlink test uyumluluğu. Hesap/anahtar veya fiziksel cihaz gerektiren işler burada yapılmış sayılmaz.

## Önceki durum kayıtları

## Kuyruk meşgul yarışı düzeltmesi — 14 Ekim 2026

- Aynı kullanıcı için görev sahipliği ilk kuyruk kontrolünden sonra değişirse iş bloke edilmek yerine aynı görev kimliğiyle bekler. Sonraki tur mevcut günlüğü kullanır; tamamlanmış adımlar ve iptal korunur.
- Kurtarma, kayıtlı görev planını ve kuyruk kimliğini ilk zamanlanan planla karşılaştırır; farklı girdi/ajan/bağımlılık veya başka kuyruk kaydı çalıştırılmaz.
- Doğrulama: 47 odaklı test ve tam sürüm kontrolü geçti (1045 Python testi, 2 atlanan; 22 JavaScript grubu, 6 smoke grubu). Meşgul yarışları, tekrar yürütmeme, iptal ve değişmiş plan/kuyruk kaydı reddi sınandı. Gerçek Windows kabulü ayrıca yapılmalıdır.

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

## Windows symlink test düzeltmesi

Normal Windows kullanıcısında WinError 1314 nedeniyle iki test gerçek sembolik bağ oluşturamıyordu. Boş/bozuk veri ve sembolik bağ reddi her ortamda çalıştırılır; gerçek dosya sistemi bağ testi ayrı tutulur ve yalnız WinError 1314 için atlanır. Diğer OSError hataları gizlenmez. Üretimdeki sembolik bağ koruması değiştirilmedi.

## Güncel depo: Jarvis-v2

GitHub okuma/güncelleme ve kaynak yayınlama hedefi `hamdkose-ctrl/Jarvis-v2`, dal `main`. Yeni sürüm kaydı `~/.jarvis/update-Jarvis-v2.json`; eski `update.json` değiştirilmez ve yeni deponun commit tabanı sayılmaz. İlk kullanımda GitHub doğrulaması kaynakların eşitliğini kanıtlamadan taban commit kaydedilmez. Taban bilinmiyorsa normal kurulum güvenli biçimde durur. Açılış kontrolü kaynak kurmaz. Mevcut GitHub anahtarının yeni özel depoya erişimi ayrıca gerekir; token/hesap otomatik değiştirilmez. Kullanıcı daha yeni ZIP gönderirse kaynak farkları doğrulanır; eski depo taban alınmaz.

## Video araçları kurulumu ve çalışma testi

Windows'ta isteğe bağlı `scripts/video_kurulum.bat`, kullanıcı Evet seçerse yalnız `winget install --id Gyan.FFmpeg --exact --source winget --scope user` çalıştırır. Uygulama kendiliğinden kurulum/indirme yapmaz. WinGet eksikse App Installer veya FFmpeg'in Windows dağıtımı gerekir. WinGet sonucu başarısızsa başarı denmez; kurulumdan sonra Jarvis yeniden başlatılır (PATH yenilenmesi). Paket kaynağı: https://github.com/microsoft/winget-pkgs/tree/master/manifests/g/Gyan/FFmpeg .

`video araçlarını kontrol et` / `video kurulum kontrol` yerel FFmpeg ve FFprobe sürüm çağrılarını, 0,3 saniyelik geçici H.264 kodlamayı ve gerçek dosya/codec/boyut/süre doğrulamasını yapar. Sürüm 5 sn, kodlama 15 sn, doğrulama 5 sn sınırındadır. Geçici çıktı temizlenir, ham araç çıktısı/dosya yolu gösterilmez; model/ağ/hesap/ses çağrısı yoktur. Eksik/bozuk/zaman aşımı başarı sayılmaz. Windows BAT/WinGet kurulumu gerçek PC'de ayrıca denenmelidir.

## Gmail ekleri ve eski OAuth kaydı — 14 Ekim 2026

`görev mail ekleri <mail_kimliği>` ilk 20 ekin adını, boyutunu ve metin desteğini gösterir; ek içeriğini indirmez. `görev mail ek oku <mail_kimliği> <sıra>` kesin mail kimliği ve 1–20 sıra ile en fazla 256 KiB TXT/CSV/Markdown eki metin olarak okur. MIME/uzantı/boyut/base64/metin kodlaması ve mail kimliği doğrulanır. 20.000 karakter sınırında kesilme açıkça belirtilir. Ekler kaydedilmez/çalıştırılmaz; HTML, PDF/Office, arşiv ve yürütülebilir ekler bu yolda desteklenmez. İçerik görev talimatı değildir. Mevcut Gmail salt-okuma OAuth'u kullanılır; gizlilik ve kullanıcı ayrımı korunur. Ek anlık görüntüsü özet ve gösterim tutarlılığıyla doğrulanır; canlı API ayrıca denenmelidir.

`hesap durumu` yalnız doğru `google_legacy_owner` kaydıyla eşleşen eski Google token dosyasını gösterir. Eski izin zamanı dosya veya geçerli izin kanıtı sayılmaz; sahiplik kaydı farklıysa eski token bağlantı kabul edilmez. Tanılama dosyayı taşımaz; mevcut Google bağlantı akışı kendi sahiplik kontrollü geçişini yapar.

## PDF ve Office Gmail ekleri — 14 Ekim 2026

Mevcut `görev mail ek oku <mail_kimliği> <sıra>` artık en fazla 4 MiB PDF/DOCX/XLSX/PPTX ekini ayrı Python sürecinde, 30 sn sınırıyla metne çevirir. TXT/CSV/Markdown 256 KiB sınırı korunur. Ek byte'ları stdin ile aktarılır; ek dosyası kalıcı veya geçici diske yazılmaz. PDF ilk 40 sayfa ve 20.000 karakterle sınırlıdır; kesilme belirtilir. Görüntü/taranmış, şifreli/bozuk veya okuyucu eksik belgeler okunmuş sayılmaz; OCR/ağ/model çağrısı yoktur.

Office arşivi 512 giriş/16 MiB açılmış toplam/4 MiB tek dosya sınırındadır; şifreli, makrolu ve aşırı sıkıştırılmış girdiler reddedilir. Yalnız metin XML'i okunur; XML DOCTYPE/ENTITY kabul edilmez, dış ilişkiler takip edilmez. Excel yalnız kayıtlı hücre değerlerini gösterir; formül çalıştırılmaz ve kayıtlı sonuç yoksa açıkça belirtilir. Slayt/Word metni okunur; görseller, düzen, notlar ve formüllerin anlamı tam korunmuş sayılmaz. Eski ikili DOC/XLS/PPT ve makrolu DOCM/XLSM desteklenmez.

Doğrulama: gerçek PDF/Word/Excel/PowerPoint örnekleri, metinsiz PDF, makro/XML varlığı/açılmış boyut reddi, tür/boyut sınırı, süre aşımı ve bozuk alt süreç çıktısı. Canlı Gmail ve gerçek Windows alt süreç kabulü ayrıca gerekir.

## Türkçe büyük İ ile ek komut yönlendirmesi

“İlk mailin eklerini göster” ve “İlk mailin ilk ekini oku” casefold sonrasında birleşik nokta nedeniyle tanınmıyordu; karşılaştırmada bu nokta normalize edilir. Mail kimlikleri ve dosya metinleri değiştirilmez. Gerçek komut yönlendirici üzerinden büyük İ ile listelenen/okunan ek komutlarının modele veya eski posta yoluna düşmediği sınanır. Yeni kod uygulanınca Jarvis kapatılıp yeniden başlatılmalıdır; çalışan eski süreç kodu bellekte tutar.

## Otonom kod yürütme — 15 Ekim 2026
Uygulandı: araç yanıtını doğrulama, sınırlı şema düzeltmesi ve otomatik modda başka onaylı ücretsiz sağlayıcı; yeni göreve ait gerçek unittest testi ve mevcut proje kontrolleri; başarısız testten düzeltme; dosya ve test günlüğü teslimi; test öncesi kesilmiş görevi güvenli checkpoint ile sürdürme. Kaynak uygulama/gönderim/ücretli havuz kuralları korunur.
Açık: gerçek PC'de model hesabı ve kota ile üretim kabulü; Windows süreç/UTF-8 kabulü; eksik yerel modelin kurulması ve cihaz kapasitesi gibi ortam onarımları; kod dışındaki bütün görevlerin kendiliğinden yeni araç geliştirmesi. Bu değişiklik genel sınırsız otonom asistana ulaşıldığı iddiası değildir. Donanım değişimi fiziksel işlem ve kullanıcı kararı gerektirir.

Groq seçili modeli bulunamaz/kotaya takılırsa mevcut listeden sınırlı alternatif model denemesi eklendi; başarısı kullanıcıya özel önbelleklenir. Modellerin gerçek hesaptaki erişimi/kotası canlı API ile doğrulanmadı.

## Ortak hedef yürütücüsü — 15 Ekim 2026
Uygulandı: kodla sınırlı olmayan ortak planla/çalıştır/doğrula/toparlan döngüsü; araştırma, hesap/mail, rapor, belge, medya, uygulama keşfi, masaüstü, ekran/kamera, sistem, not/hafıza/ayar ve zamanlama araçlarını birlikte kullanma. İlerleme kalıcı, bilinen başarısız okumada alternatif yöntem mümkün; kesilmiş dış etkide kayıtla doğrulama yapılır, belirsiz işlem yinelenmez. Eski görev komutları ve izin kapıları korunur.
Doğrulananlar: gerçek dosya/rapor, DOCX dönüşümü, kısa FFmpeg videosu, kullanıcıya ait kuyruk kaydı, hata sonrası alternatif araç, çok hedef, onay ve kesinti senaryoları. Ağ/model ve Windows cihazı sınırları taklit edilmiştir.
Açık: Hamdi'nin PC'sinde yeni çok araçlı hedefin canlı modelle uçtan uca kabulü; hesap yetkisi/kotası ve gerçek uygulama/cihaz davranışı. Eksik program kurma, sınırsız shell veya fiziksel RAM değişimi bu sürümde araç değildir. Mevcut tek adımlı hızlı yollar korunmuştur; her doğal dil ifadesinin kusursuz yorumlandığı iddia edilmez.
Son doğrulama: 1186 Python testi OK (2 Linux/Windows farkı atlaması), 23 Node ve 6 smoke grubu başarılı. Ayrı gerçek main.handle girişinde tek hedef isteğiyle rapor+FFmpeg video dosyası üretildi ve dosya/medya kanıtları denetlendi; main._live_command girişi aynı yürütücüyü çalıştırdı. Model/cihaz/hesap sınırları taklit edildi; gerçek mikrofon testi yapılmış sayılmaz. Salt okunur son kural denetimi geçti.

## Eski test sözleşmesiyle resmî güncelleme — 15 Ekim 2026
PC kaydındaki iki hata eski testlerin yeni geliştirme sözleşmesine bindirilmesinden: gerçek yeni kod testi istemeyen model senaryosu ve deliver_code'u taklit etmeden kilitli alandan teslim bekleyen worker testi. Resmî güncelleme iki sürümü ayrı test eder; geliştirici taslakları mevcut güvenilir bindirme yolunu korur. Bir defalık geçiş betiği diskte test değiştirerek değil, resmî doğrulayıcıyı bellekte kullanarak normal kurulum işlemini çalıştırır. Windows canlı geçiş kabulü açıktır.

Doğrulama tamamlandı: PC kaydındaki iki hata aynı eski test dosyalarıyla birebir üretildi. Gerçek eski kaynak/test kopyasından yeni sürüme çift doğrulama geçti; adayda 1193 Python testi OK (2 atlama), 23 Node ve 6 smoke başarılı. Yedi yeni regresyon; farklı sürüm manifesti, kötü aday reddi, taslak test koruması ve geçiş yardımcısının normal updater kapısını kullanması dahil. Eski kurulum için resmî geçiş yardımcısı gerekir; canlı Windows kabulü açık.

## Rapor/video hedefinin geliştirme kilidinde durması — 15 Ekim 2026
PC kabulünde rapor+3 saniyelik yazılı video için coder seçildi; geliştirme kilidi işlem belirsizliği sanılıp hedef review durumuna düştü. Worker öncesi kesin kilit kontrolü, writer/media kullanım talimatı ve yalnız bu eski kesin ret kaydını sürdürebilme eklendi. Gerçek FFmpeg video ve rapor dosyası ile yanlış araçtan toparlanma sınanır. Geliştirme kilidi veya kaynak uygulama sınırı gevşetilmez. Gerçek modelin PC'deki araç seçimi ayrıca kabul gerektirir.
Son kontrol: 1195 Python testi OK (2 platform atlaması), 23 Node/6 smoke başarılı. Ortak yürütücü odaklı 37 test geçti; rapor ve tam 3 saniyelik FFmpeg dosyası gerçek üretildi. Salt okunur son denetim geçti. Mevcut hedef güncelleme ve yeniden başlatma sonrası `hedef devam` ile sürdürülebilir.


## Ekip merkezi kapsamı — 15 Ekim 2026
- Kullanıcıya özel uzman dizini, gerçek hedef/görev/kuyruk görünümü ve açık kaynak takip formu bu dalda uygulanmıştır. Roller mevcut araçları kullanır; yeni finans veri sağlayıcısı, mağaza API'si, otomatik MCP/API servis keşfi veya her role ayrı model kurulmuş değildir.
- Gerçek servisler için kullanılacak mağaza platformu ve hesap/veri bağlantıları henüz seçilmedi. Anahtarlar sohbetten veya depodan alınmaz, mevcut yerel bağlantı akışları kullanılır.
- Kesintisiz sunucu/PC kapalı çalışma, piksel ofis sahnesi ve içerik düzeyinde finans/medya kalite doğrulaması tamamlanmış değildir. Mevcut doğrulama dosya/araç kanıtını denetler.
- Windows kabulü en sonda tek listedir: Menü → Ekip merkezi; bir hedefin adımlarını izle; yeni uzman ekleyip yeniden açılışta kaldığını doğrula; kaynak takibini kaydet/iptal et; rapor dosyasını değiştirip Kanıtları kontrol et; kullanıcı değiştirince önceki kullanıcının kayıtlarının görünmediğini doğrula. Canlı model/hesap ve cihaz testi burada yapılmış sayılmaz.

### Ekip merkezi ikinci teslim — 15 Ekim 2026
Uzman düzenleme/devre dışı bırakma, çalışan ayrıntısı, kimlik ve içerik imzasıyla hedef yanıt/onay/iptal, görev sürdürme/iptal, takibi duraklatma/açma/sıklık değiştirme ve gerçek adımlara bağlı 2D ofis bu dalda eklenmiştir. Önceki ofis yapılmadı ve bu kontroller yok notları ilk teslimin tarihsel sınırlarıdır. Ofis sade yerel CSS çizimidir; AgentSpace görselinin veya varlıklarının kopyası değildir. Diğer tarafın yürütme/yetenek/servis bağlantısı çalışması devam eder; ortak kabul ve canlı Windows testleri henüz tamamlanmış değildir.


## Bağlantı çalışması — PR #28 üzerinde entegrasyon

Taban: `81f8536ab792980c2bf48c4f5a2225dd021e2fdc`. Kaynak takibi, servis referansı değerlendirmesi, sabit genel GET bağlama ve CSV alan araçları bu PR kapsamındadır. Gerçek hesap bağlantıları ve Windows canlı kabulü ayrıca doğrulanır.

Bekleyenler: gerçek Windows bildirim/yeniden başlatma kabulü; dış HTTP kaynaklarına canlı erişim; yeni banka/mağaza hesap adaptörleri ve MCP sunucusu çalıştırma (bu çalışmada tamamlanmış değildir). API listesinde bulunmak hesap bağlantısı veya ücretsiz kullanım doğrulaması değildir. Ortak kontroller bitmeden main'e birleştirilmez.

## Canlı araştırma–rapor testi — 15 Ekim 2026
Windows testi başarısız: model beklemesi, siberrecete.com DNS hatası, bilgi vermeyen yanıtın başarı sayılması ve eski yıl varsayımı görüldü. Kaynak değiştirildiği hâlde rapor teslimi tamamlanmadı. Bu geliştirme model beklemesini sınırlama, durum sorgusunu ayırma, kanıtlı araştırma ve aynı hedefte dosya teslimi regresyonlarını içerir; gerçek Windows tekrarı yapılmadan bu canlı test geçmiş sayılmaz.


## Model erişimi canlı sonucu — 15 Ekim 2026 akşam
Hedef durum sorgusu bekleme sırasında yanıt verdi. Araştırma–rapor teslimi geçmedi: Gemini HTTP429, Ollama LocalModelError; Groq deneme listesinde yoktu. Groq'un PC'deki kesin atlama nedeni henüz doğrulanmadı. Yeni düzeltme atlama nedenini ve kalan süreyi görünür kılar; tamamlanmayan hedefin eski yeşil model izini kaldırır. Hesap onayı/kota/anahtar otomatik değiştirilmez.
Kullanıcının sonraki canlı sonucu: Groq anahtarı eksikti, yeniden eklendi; ardından Groq üç farklı modelde HTTP429 döndürdü. Bu yeni sonuçta Groq'un havuza girdiği doğrulandı, başarılı model erişimi doğrulanmadı. Kota/hız sınırı ve yerel Ollama erişimi canlı kabulü bekliyor.

429 açıklaması düzeltmesi: Bu yanıt günlük kotanın dolduğu kanıtı değildir; dakika/gün istek ve token sınırları ayrıdır. Yerel ölçümde planlayıcı sabit kural+katalog+varsayılan uzman bağlamı yaklaşık 19.141 karakterdi (görev metni hariç). Katalogdaki tekrar eden sütun adları kayıpsız sıkıştırıldı (14.871 → 11.171 karakter); planlayıcının çıktı bütçesi 4.000 → 1.200 token oldu. Gerçek Groq token sayımı ve PC'de hangi sınırın tetiklendiği doğrulanmadı. Resmî kaynak: https://console.groq.com/docs/rate-limits .


## Ortak main bütünleştirmesi — 16 Ekim 2026
- PR31 model seçim nedenleri/429 açıklaması ve planlama bağlamı güncellemesi, Selçuklu arka planı ve eski gmail-attachment-followups dalının eksik kısa komut/kimlik koruma/boş ek davranışı aynı adayda doğrulandı. Güncel UTF-8 belge protokolü ve sade sonuç gösterimi korundu.
- Tam paket: 1256 Python testi, 1 Windows DPAPI atlaması; 25 Node ve 6 smoke başarılı. Chromium tam frontend + taklit API: ana ekran, mevcut hologram, yeni arka plan görünürlüğü, menü dönüşleri, tek katman, dar ekran ve reduced-motion geçti. Canlı model/hesap çağrısı yapılmadı.
- Bekleyen gerçek PC: açılışta önce manzara, sonra aşağıdan hilal-yıldız, sonra kırmızı enerji; Gmail ek listesi → kısa ek okuma; mevcut hedefi sürdürerek kaynaklı rapor teslimi. Model servislerinin 429 yanıtı/kullanıcı kotası ve Ollama erişimi bu birleştirmeyle giderilmiş sayılmaz. Selçuklu karakteri henüz uygulamaya bağlanmadı; mevcut hologram korunur.


## Kayıtlı hedefi yeniden planlama döngüsü — 16 Ekim 2026
Canlı PC'de genel duraklama mesajı ve araçsız hedefler görüldü. Modelin kayıtlı hedefte yeniden plan önermesi artık üç retle sınırlanır, plan korunduğu açık yazılır. Planlayıcıya bu çağrıda plan bulunduğu belirtilir. Gerçek sağlayıcıyla mevcut hedefin araç adımlarına geçip raporu tamamlaması hâlâ kullanıcı kabulü gerektirir.


## Kaynak keşfi ve çalışma ekranı — 16 Ekim 2026
- Mevcut data/headlines aracı isteğe bağlı query ile gerçek dizin/RSS bağlantılarını konuya göre sıralar; tarih veya makale adresi üretmez. Başlık listesi içerik kanıtı değildir. Planlayıcı başarısız sayfadan sonra dizin keşfi, research, writer ve verify araçlarına yönlendirilir; aynı hedef korunur.
- Kanıt alınamayan sayfalarda erişim ve içerik sorunları aynı şeymiş gibi sunulmaz. Rapor eki bu sınırı açıklar.
- Ekip/sohbet/çalışma panellerinde Selçuklu zemini karartılır; ana ekran ve düz menü görünümü korunur. Yeni API/model çağrısı veya bağlantı eklenmez.
- Regresyon: başarısız kaynak → gerçek bağlantı keşfi → alıntılı araştırma → gerçek rapor dosyası → verify zinciri model/ağ sınırları taklit edilerek sınanır. Canlı kaynak kapsamı, yayın tarihi doğruluğu ve Windows model davranışı ayrıca kullanıcı kabulünde doğrulanmalıdır.


## Tekil haber kanıtı ve son tamamlanma — 16 Ekim 2026
- Haber/gelişme/duyuru/tarihli araştırmalarda mevcut HTTPS kaynak okuyucusu üzerinden tekil haber gövdesi, başlık ve makaleye ait datePublished/article:published_time/yayın etiketli time aranır. Kategori sayfası, menü metni, yalnız dateModified ve belirsiz tarih başarı sayılmaz. Gelecek veya istenen gün aralığı dışındaki haber reddedilir. Bu kontrol tarih metaverisinin yayıncı tarafından doğru girildiğini garanti etmez.
- Haber çıktısı modelin serbest özetini değil, tarih ve gerçek kaynak alıntılarını taşır. Haber raporu bu makbuzlardan deterministik Markdown olarak oluşturulur; ek writer model çağrısı, uydurma tarih veya iç içe bağlantı üretilemez. Dosya denetimi bu raporun içerik kaydıyla eşleşmesini de denetler. Genel raporlar ve mail taslakları mevcut model yolunda kalır. Haber raporu birebir kaynak alıntısı sunar; anlamsal doğruluk ve tüm kurumların kapsanması garantisi vermez.
- Sürdürmede eski haber/makale tarih kanıtı olmayan research ve writer çıktıları, bağımlı teslim ve hedef kanıtları geçersizleşir; hedef kimliği ve eski dosyalar silinmez. Belirsiz dış etkide mevcut review kapısı korunur.
- Bütün alt hedefler açık complete adımıyla tamamlanıp mevcut kanıtları doğrulandıysa son finish için yeni model çağrısı yapılmaz. Sadece dosya veya verify sonucu görülmesi, bekleyen hedefleri otomatik tamamlamaz.
- tests/test_news_research.py ve hedef regresyonları: kategori/yanlış tarih/menü reddi, gerçek rapor dosyası, içerik-bağlı doğrulama, eski kayıt sürdürme ve son çağrıda 429 gerekmemesi. Ağ/model taklit edilir. Canlı Windows kaynak erişimi, gerçek modelin kaynak seçimi ve yayıncı metaverisi kabulü ayrıca doğrulanmalıdır.
- Son doğrulama: 1.276 Python testi (Windows DPAPI 1 skip), 25 JavaScript grubu ve 6 smoke grubu başarılı. 109 ilgili regresyon başarılı; son salt okunur kural denetimi geçti. Canlı model/Windows kabulü yapılmadı.


## Kısa sürdür komutu ve kaynak dizini — 16 Ekim 2026
- sürdür/surdur/hedef sürdür/hedef surdur mevcut devam komutlarıyla aynı kayıtlı hedef yoluna, genel dispatch ve model sınıflandırmasından önce gider. Hedef kimliği korunur; komut kullanıcı yanıtı olarak kayda eklenmez. Sürdür bir onay değildir; approval/review kapıları korunur.
- Haber dizinindeki resimli/aria-label/title bağlantıları metin boşsa bu gerçek etiketlerle keşfedilir. Sayfada okunabilir bağlantı yoksa yalnız sayfanın açıkça ilan ettiği aynı-host RSS/Atom adreslerinden en çok ikisi mevcut güvenli HTTPS okuyucusuyla denenir. Adres tahmini veya yeni servis yoktur; bulunan akışın URL/hash kaydı tutulur. İzin/iptal hatası yutulmaz. Kaynak erişimi veya tam haber kapsamı garantisi değildir.
- İlgili regresyonlar kısa komutun erken yönlendirilmesi, aynı hedef/yanıt kaydı, onayın korunması, gerçek etiket bağlantıları, yabancı feed reddi, sınırlı fallback ve feed içerik özeti eşleşmesini sınar. Model/ağ taklit edilir; gerçek sağlayıcı kotası ve PC Ollama yapılandırması bu değişiklikle düzeltilmiş sayılmaz.


## Model yokken sınırlı yapay zekâ kaynak raporu — 16 Ekim 2026
- Planlayıcı RuntimeError ile durduğunda yalnız kullanıcının açık yapay zekâ haber araştırması + rapor dosyası isteği için news_recovery çalışabilir. Mevcut görevde daha önce denenmiş en çok iki kaynak adresinden mevcut data/headlines ile bağlantı keşfeder; en çok dört adayı mevcut research okuyucusuyla dener. Adres uydurmaz, yeni hedef/kuyruk/model oluşturmaz. Toplam 10 kurtarma adımı ve mevcut 96 adım sınırı korunur.
- Kaynak-only research runtime kimliğinden gelir, model aracı girdisi değildir. Tekil makale/yayın tarihi sınırları aynıdır; gövdede gerçek yapay zekâ ifadesi içeren en çok üç birebir alıntı seçilir. Model çağrısı ve anlamsal yorum yoktur. Writer/verify mevcut araçlarla kısmi rapor oluşturur; sonuç URL, tarih ve alıntı kaydıyla eşleşir.
- Kısmi rapor dosyası render edilir; kapsam/tüm kurumlar doğrulanmadığından hedefler otomatik tamamlanmaz. Sürdürmede doğrulanmış aynı teslim yeniden yazılmaz veya kaynaklar körlemesine tekrarlanmaz. İptal, sahiplik, approval/review ve gizlilik sınırları korunur. Ağ erişimi/dizin/tarih yoksa dosya teslimi garanti edilmez; bulut kotası ve iş PC'sinde olmayan Ollama bu kodla kullanılabilir hâle gelmez.
- Kurtarma yalnız planlayıcı erişilemezliğinde tetiklenir; normal araç/tur bütçesi hatasında tetiklenmez. Kalan 24 araçlık tur bütçesi aktarılır ve diğer sınırlarla birlikte uygulanır. Gerçek dosyalı quota regresyonu ve tekrarın yeni dosya/ağ çağrısı üretmemesi doğrulandı; son salt okunur denetim geçti.
