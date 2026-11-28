# Masaüstünde Jarvis

- Windows’ta maskot varsayılan başlangıç yüzeyi. İlk pencere hazırsa Komut Merkezi kullanıcının isteğiyle açılır. Ayar kapalıysa ya da pencere kurulamıyorsa önceki açılış akışı kullanılır. Maskotlu akışta eski küçük pencere açılmaz.
- Maskota tıkla ve konuş. `Ctrl+Alt+J` ile yazı kartını aç. Sağ tık menüsünden kısayolu değiştir, mikrofonu yönet, maskotu gizle veya Komut Merkezi’ni aç. Tepsi, gizlenen maskotu geri getirir.
- Cevaplar ve durumlar mevcut Hub olaylarından gelir. Masaüstü dinleyicileri tarayıcı istemcisi sayılmaz. Kullanıcı değişince açık kart, ek, yanıt ve görev seçimi temizlenir. Bildirimler başka pencerenin odağını almadan gösterilir.
- Dosya seçiminde mevcut izinli kökler kullanılır. Görevler aynı Core görünümünden okunur ve hedef kimliğiyle yönetilir. Ayrıntı düğmesi Komut Merkezi’nde ilgili işi seçer. Teslim kaydetme doğrulanmış dosya baytlarını kullanır.
- Boşta hareketler aralarda bir kez oynar. Konuşma hareketi mevcut ses oynatma durumuna bağlıdır. Windows hareket azaltma ayarı ve gizli maskot, kare oynatmayı durdurur.

# Tek konsol görünümü — 23 Kasım 2026

- Ekip İşleri ve hareket düğmesi ofis başlığında. Ekip İşleri, Hafıza, Yetenekler, Karakter ve Ayarlar mevcut sağ bölmede açılır. Telefon ofiste kendi görünümünü kullanır.
- Sağdaki Uzmanlar her uzmanın adını, anahtar sözcüklerini, etkinliğini ve araçlarını uzman kimliğine göre düzenler. Kaydetme mevcut profil ve ekip revizyonu üzerinden yapılır.
- Eski Sohbet ve Dosyalar sayfalarının HTML üretimi, stilleri ve arama arayüzü kaldırıldı. Eski adresler ana konsola döner. Sohbet geçmişi, mesaj vurgusu ve şifreli geliştirme ana sohbet alanında çalışır. Sohbet ekleri geldikçe hızlı işlem seçenekleri gösterilir. Düğme girdiyi hazırlar. Gönder düğmesi mevcut dosya komutunu çalıştırır.
- Çalışma Modu tek konu veya soru girişine sahiptir. Kaynak önizlemesi açılır, çalışma bölümleri bir seçim kutusunda toplanır. Mevcut çalışma, soru ve kaynak kayıtları kullanılır.
- Sohbette işlem adımları ve görev sonucu kartlarının zemin, kenarlık ve yazı renkleri konsol temasından gelir. Genel görünüm açıkken de seçili konsol rengi kullanılır.

# BRAIN-10 sonuç görünürlüğü — 14 Kasım 2026

Ekip merkezinin query projection'ı mevcut Core result_presentation servisini kullanır: kontrol edilen done adım, artifact ve receipt gösterilir; değişmiş/eksik/yanlış owner kanıtı unavailable/incomplete görünür. Projection özgün journal'ı değiştirmez. Butonların terminal kararı ve control fingerprint'i özgün record_state/kayıttan gelir; yalnız görünüm eksildi diye kapanmış task'a continue/stop önerilmez. İncomplete işler dikkat sayacına ve açık ayrıntıya dahil edilir. Kanıtı kontrol et butonu aynı Core/query sahibine gider; UI verifier, worker veya ikinci GoalState değildir.

---

# BRAIN-09 Hafıza tercihleri — 14 Kasım 2026

Hafıza ekranında sunumun9 kapalı tercihi mevcut Profile sahibine `pref_set` ile yazılır. Etkin değerin açık/öğrenilmiş/default kaynağı gösterilir; açık seçim kaldırılır veya learned öneri ayrı silinir. Bridge Core persona servisini çağırır; UI anlam/izin kararı üretmez. Render response owner ile snapshot owner'ı eşleştirir; select/button event'i de güncel owner'ı tekrar kontrol eder. Geç eski kullanıcı cevabı/yazımı yeni kullanıcıya uygulanmaz. Alan notu: `docs/agents/persona.md`.

---

# Masaüstü arayüzü — 21 Kasım 2026

- Masaüstü `/nx.html` üzerinden tek ana konsolla açılır. Sol sütun dünya haritasını ve bugünün takvimini, orta sütun çekirdeği ve hareketli ofisi, sağ sütun yazılı ve sesli iletişimi gösterir. Haber düğmesi aynı girişe bir komut hazırlar. Gönderimi kullanıcı başlatır.
- Ana konsol mevcut sohbet, dosya ekleme, ses ve ekip sahiplerini kullanır. Sohbet geçmişi, ekip özeti ve notlara aynı konsoldan erişilir. Haritadaki işaretler sabit konumlardır. Ofis canlandırması yerel olarak çizilir; gerçek işler Uzman görünümündeki `team_snapshot` projeksiyonundan gelir.
- Üst çubuktaki Tema seçimi tarayıcıda saklanır. Çekirdek, sol araçların rengi ve motorun ses durumuna tepki verir. Azaltılmış hareket tercihinde çizim durağandır. Önceki ana ekranın HTML'si, stili ve avatar dosyası kaldırıldı.
- Ekip Merkezi seçili çalışmanın adımlarını yanında gösterir. İptal, devam, soru ve onay mevcut team_control ve aynı Core kimliğini kullanır. Form taslağı yalnız aynı işlemin kontrol imzası korunurken yenilemede saklanır. Kullanıcı değişince eski sonuçlar gösterilmez. Uzman, kaynak, kuyruk ve doğrulama araçları mevcut sözleşmelerle çalışır.
- Teslim indirme, team_artifact üzerinden seçili işin etkin kullanıcıya ait kabul edilmiş adımını yeniden okur. Kanıt, benzersiz dosya adı, izinli kök ve okunan baytların özeti eşleşmesi gerekir. En çok 16 MB. İndirme sonucu işin durumunu değiştirmez.
- Dosyalar sayfasında arama ve liste solda, seçili dosya ve işlemleri sağdadır. `file_preview` etkin kullanıcıyı ve mevcut dosya köklerini denetler. İlk PDF sayfası mevcut PDFium okuyucusunda, desteklenen görseller Pillow ile yerelde küçültülerek çizilir. En çok 20 MB kaynak okunur. Yanıt yalnız istek sahibi ve seçili dosya hâlâ eşleşiyorsa gösterilir.
- Ayarlar: tek sayfa, mevcut form ve araç sahipleri. Sol bölüm seçimi, Ayarlarda ara, sağlayıcı kartları, ses, hesap, gizlilik ve GitHub işlemleri korunur. Gönderme, pencere ve onay kontrolleri mevcut yerel /api köprüsünü kullanır.
- Paylaşım, ana konsolun Görsel Alan sekmesinden, Ekran ve PC sayfasından veya ortak yazı çubuğundan açıkça seçilir. Ana konsolda yalnız çekirdek alanında önizlenir. Ekran ve PC sayfası kendi önizlemesini gösterir. Kamera ve Windows işlemleri gerçek cihazda ayrıca doğrulanır.
- Motorun user, assistant ve step olayları aynı istek kimliğiyle sohbete bağlanır. Telefon kullanıcı verisi farklı PC profiline gösterilmez. Yetkisiz HTTP, yerel oturum ve istek gövde sınırları mevcut web.py sahiplerindedir.

## Router V2 bağlantı alanı —14 Kasım2026

Yapay Zekâ alanı hazır Gemini/Groq/Cloudflare/isteğe bağlı yerel profilleri ve ayrı Özel API formunu sunar. Hazır rol sırası kullanıcı priority editörü değildir; ek API'ye Brain/sohbet/araştırma/uzun iş/vision rolü verilir. Hazır OpenAI/Claude kartları ve eski paid activation eylemleri emeklidir; generic protokol seçenekleri vendor seçimi değildir. Eski kayıtlar kapalı custom olarak görünür, key formda gösterilmez. Kaydetme/açılış inference yapmaz; tek test ayrıca açık tercihtir ve ücretsiz/rol kabulü sayılmaz.

Hazır Gemini, Groq ve Cloudflare kartında anahtarı kaydet ve bağlantıyı dene. Cloudflare hesap kimliğini de ister. Gemini konuşma ve seçilmiş içerik izinleri ayrı ve geri alınabilir. Kaydedilen anahtar tek başına bağlantıyı doğrulamaz. Kart gerçek yanıtı veya kota hatasını, Otomatik Model Seçimi son sohbeti yanıtlayan modeli gösterir. Hazır profillerin ücretli/ücretsiz beyanı ve yerel kota ayarı yoktur. Özel API alanında çağrı sınırı ve isteğe bağlı harcama sınırı ayarlanır.

İstek izleri owner/request/attempt ve policy/model/ana-yedek/ret/gerçek usage/reservation ayrımını gösterir; bilinmeyen null/ölçülmedi olur. Async save/test/model listesi cevapları ve değişiklikleri beklenen owner ile çitlidir; owner değişince önceki form/mesaj/model listesi gösterilmez. Bridge argüman sözleşmeleri ve gerçek HTTP/Chromium akışı ayrı doğrulanır. Kaynak/göç: `docs/architecture/JARVIS_ROUTER_V2_IMPLEMENTATION_AND_RETIREMENT_MAP.md`.

Hazır Cloudflare kartı owner Account ID/token kaydını mevcut image_gen key sahibine bağlar; kayıt/silme API veya model çağırmaz. Özel API için ayrıca açık **tek sentetik görüntü denemesi** vardır: beklenen kod yalnız görüntü piksellerindedir; doğru okuma endpoint/protokol/model/secret/revision taşıyıcısına süreli vision gözlemi bağlar. Bu, genel görüntü doğruluğu veya Brain rol kabulü değildir; metin bağlantı testi/checkbox vision açmaz, bağlantı değişimi gözlemi geçersizleştirir.

## Teslim makbuzu — 17 Kasım 2026 (PR-5)

- `engine_background._emit_for` pencere geri çağırmasını yutar ama artık iz bırakır: callback gerçekten fırlattıysa `_record_failure` yazılır ve fonksiyon `False` döner; her normal yol `True`. Yalnız ön-plan kullanıcısında UI koluna bakılır; yazılı olay kuyruğu (event_log/history) UI hatasından bağımsızdır.
- `event_channels.deliver` UI sink'i `is False` sonucunda `RuntimeError` yükseltir; `event_fanout` bunu `ui: failed:RuntimeError` olarak makbuza yazar. `None` dönen eski test klempleri "delivered" sayılmaya devam eder (davranış değişikliği yalnız gerçek hata yolundadır). Hiçbir sahip-kanalı teslim edilmezse deliver hata eder; çağıran kaydı teslim-edilmedi olarak tutar.
- `canonical_goal_flow._accepted_user_channel` yalnız `ui`/`ntfy` kanallarının tam `"delivered"` değerini kabul eder; `log`/`voice` tek başına makbuz değildir. Bu kabul insan tarafından okundu garantisi değildir — eski sözleşmeyle aynı: sink'in kabulü, end-to-end exactly-once değil.
- Kanıt: `tests/test_delivery_receipt_honesty.py` (16 test, pencere/telefon/model çağırmaz). Gerçek arayüz gecesi canlı kabul olarak ayrıdır.

## Eklenti listelemesi eklenti kodunu yürütmez — 18 Kasım 2026

- `plugins.listing()` (Ayarlar › eklenti kartları ve `web.py` yetenek sayacı) artık her `.py` dosyasını `ast.parse` ile okur; `NAME`/`DESCRIPTION` yalnız sabit dizgi atamasından, `handle` varlığı fonksiyon tanımıyla dosyanın kendi gövdesinden gelir. İmport modülü (`exec_module`) yalnız `plugins.handle()` gerçek komut dispatch'indedir: Ayarlar'ı açmak, listelemek veya saymak kullanıcı eklenti kodunu çalıştırmaz.
- Sabit olmayan `NAME` (ör. `os.getcwd()`) yürütülmez, dosya gövde adı (stem) varsayılan kalır. Bozuk sözdizimi yalnız kendi satırını `ok=false` + hata adıyla raporlar; diğer eklentiler ve Jarvis düşmez. `handle` yoksa aynı kayıtta neden olarak yazılır, komut yolunda zaten yürütülmez.
- Okunamayan dosya (OSError) sessiz başarısız sayılmaz; kayıt `error` alanıyla listelenir. Kanıt: `tests/test_plugin_listing_safety.py` (6 test; yan etme olarak dosya yazan eklenti tek kanıttır — `listing()` sonrasında dosya yoktur, `handle()` sonrasında vardır).
- Aynı paketin profil tarafı: profil kaydı hiç okunamazsa (OSError) sessiz `pass` kalktı, `profile_unreadable` bayrağı + `jarvis.profile` uyarısı var ve o kaydın üzerine hiçbir save yazılmaz. Ayrıntı: `docs/agents/persona.md`, `tests/test_profile_data_safety.py`.

- **Kullanılmayan arayüz/üretim yardımcıları silindi (18 Kasım 2026, ölü sembol göçü):** `richtext.inline_parts` + `INLINE` (satır içi bold/mono ayrıştırıcı) ve `vision.preview_b64` üretimde hiç çağrılmıyordu. Ekran önizlemesinin tek sahibi `vision.preview_multi` (`web.py` → `preview_multi((480, 270))[0]`), seslendirme temizliğinin tek sahibi `richtext.speakable`/`split_blocks`tır. Aynı turda silinen diğer çağrısız yüzeyler ve kalan sahipleri: `llm.OLLAMA_BIG_MODEL` (yerel model seçimi gerçek kurulu katalogdan), `when.WEEKDAYS_TITLE` (gün adları `when.WEEKDAYS`), `proactive_advisor.PRIORITIES` (öncelik `SuggestionPolicy.priority`), `codegen.scaffold` (kod üretimi `codegen.generate` ve tek kod bloku sözleşmesindedir), `brain_understanding.notes_read_view` (not okuma argümanları `_notes_arguments` + Core `core_plan` kapısı). Kanıt: `tests/test_dead_symbol_retirement.py` (15 test; yokluk + sahip canlılığı). Sunum davranışı değişmedi.

- Dosya listesi önbelleğinde tek yenileme yolu `nxapi.list_files(force=True)`dir; arayüzün "yenile"si de bunu kullanır. Test izolasyonu için üretime açık duran `nxapi.reset_file_cache` 18 Kasım 2026 ölçümünde üretimden hiç çağrılmıyordu ve kaldırıldı — belgelediği "yenile düğmesine ayrı zorlama yolu" iddiası gerçek sahibiyle (force) aynı şeydi. Test artık soğuk önbelleği kendi içinde kurar ve eski kopyayı geri koyar: `tests/test_repair_regressions.py`. Üretimde test hook'u bırakılmaz; negatif kilit `tests/test_dead_symbol_retirement_phase2.py`.

- Küçük Jarvis şeridinin çizim sahibi tek modüldür: `modules/widget.py` kendi renk sözlüğü (`COLORS`) ile çalışır. `modules/widget_styles.py` (FAMILIES/validate/draw sözlüğü) 18 Kasım 2026 taramasında depo genelinde hiçbir yerden adlandırılmayan yetim bir dosya olarak ölçüldü ve silindi; ZIP aktarımından (`8d46466d`) kalma, hiç kullanıcı akışına bağlanmamıştı. Arayüzde görünen davranış değişmedi. Kilitle: `tests/test_dead_symbol_retirement_phase2.py` (`OrphanModuleIsGoneTests`, `test_live_widget_owns_its_own_drawing`).

---

## T5 masaüstü maskot penceresi — 27 Kasım 2026

- **Ayrı pencere, web maskotu değişmedi:** `modules/mascot_window.py` yalnız Windows'ta, `mascot_window` ayarı açıksa `web.main` içinden ayrı bir Tk iş parçacığında `Toplevel` açar. `/nx.html` içindeki `webui/mascot.js` maskotu ve klipleri aynen kalır; iki pencere birbirini beslemez.
- **Durum kaynağı tek:** oynatıcı `web.hub.state` + `engine.flags` okur; web arayüzünün `Mascot.set(S.orb)` aldığı kaynakla aynıdır. İkinci bir durum makinesi yoktur. Bilinmeyen durum boşta sayılır; `sleep` bayrağı maskotu boşta gösterir.
- **Pencere:** `overrideredirect(True)`, `-topmost`, Windows'ta `-transparentcolor`; arka plan `#010203`. Kareler mevcut `webui/mascot/*.webp` kliplerinden açılışta **bir kez** ön yüklenir (5 dosya, 200 kare, 160×206 RGBA), DPI ölçeğinde 320×412'ye büyütülür; 30 fps döngü. Kare yoksa pencere hiç açılmaz (sessiz gizlenme).
- **Kare anahtarlama:** `key_flat(image, size)` alfayı maskeye çevirir: `alpha==0` → tam `#010203`, `alpha>0` → kaynak RGB **aynen** (yeniden boyutlandırma LANCZOS, sonra maske; `alpha_composite` yok). Böylece yarı saydam kenar pikselleri KEY rengine karışıp siyah kontur üretmez. Kanıt: `docs/evidence/t5_key_flat_compare.png`.
- **Tıklama geçişi varsayılan kapalı:** `WS_EX_TRANSPARENT` yalnız `mascot_click_through` ayarı açıksa ve durum boştaysa uygulanır (ctypes `SetWindowLongW`, `WS_EX_LAYERED` korunur); dinliyor/düşünüyor/konuşuyor durumunda geri açılır. Ayar kapalıyken sürükleme ve sağ tık menüsü **her durumda** çalışır; `-transparentcolor` zaten silüet dışındaki renk-anahtarı piksellerinde tıklamayı alta geçirir.
- **Menü ve kalıcılık:** sağ tık menüsü **Gizle / Konum sıfırla / Çık**. Sürükleme bırakıldığında konum `mascot_pos`, açılışta boyut `mascot_size` olarak `settings.json`'a yazılır. Konum her zaman en çok örtüşen (yoksa en yakın) monitörün çalışma alanına kelepçelenir; "Konum sıfırla" ana monitörün sağ altına döner. Gizle yalnız bu oturum içindir; yeniden başlatma pencereyi ayara göre yeniden açar.
- **Varsayılan kapalı:** `mascot_window` yoksa/`false` ise Tk kökü bile oluşturulmaz. Açmak için Ayarlar › Genel › **Masaüstü maskot** anahtarı (veya `mascot_window=true`) kullanılır; değişiklik **yeniden başlatınca** uygulanır. `nxapi.ui_settings` alanı `mascot_window` ve `mascot_click_through`, `ui_set` allowlist'i iki anahtarı taşır. Tıklama geçişi ayrı **Boşta tıklamayı geçir** anahtarıdır; varsayılan kapalıdır, yalnız ayar açıkken ve boşta uygulanır; değişiklik yeniden başlatma ister.
- **Ölçülen (pencere açmadan):** `tests/test_mascot_window.py` **26 test OK** — durum→kare eşlemesi (6 durum), DPI (96/120/144/192 + kelepçe), 320×412 boyut, tek/çok monitör kelepçeleme, ekran dışı → en yakın monitör, taşan pencere, sağ alt sıfırlama, bozuk kayıtlı boyut, click-through bitleri, monitör normalizasyonu, gerçek klipler (5 dosya/200 kare/RGBA/160×206), thinking↔working kare paylaşımı, bellek bütçesi, boş varlık dizini, ayar kapalıyken thread açılmaması, Windows dışı uyarısı, Tk kökünün varlığı (yoksa skip) ve yeni `key_flat`/tıklama geçişi testleri. `tests/test_nxapi_mascot_settings.py` **3 test OK**. Odaklı çalışma: `tests.test_mascot_window` + `tests.test_nxapi_mascot_settings` **29 OK** (+ `tests.test_nxapi_turn_reopen` ile **33 OK**).
- **Bellek ölçümü:** ham kareler **25,15 MB** (5×40 kare, 160×206 RGBA) + bulunulan durumun Tk fotoğrafları **20,12 MB** (40×320×412×4) = **45,26 MB** ≤ 60 MB hedefi. Yalnız bulunulan durumun fotoğrafları tutulur; durum değişince önceki küme bırakılır. `key_flat` ek bir kalıcı kare tutmaz. Boşta CPU **ölçülmedi** (pencere canlı açılmadı).
- **Kare anahtarlama ölçümü:** `bosta.webp` kare 0, 160×206: **2.818 yarı saydam kenar pikseli** (10.278 tam opak pikselin %27,4'ü); ortalama luma kaynakta **94,6**, eski `alpha_composite` çıktısında **44,8** (bağımsız ölçüm; incelemede 94,8→44,6). Yeni `key_flat` bu piksellerin RGB'sini birebir korur; `alpha==0` tam KEY. Görsel: `docs/evidence/t5_key_flat_compare.png`.
- **Manuel senaryo listesi (Hamdi'nin PC'sinde; iki ayar da yeniden başlatma ister):**
  1. Maskot her zaman üstte mi; arkası şeffaf mı (masaüstü/başka pencere üstünde)?
  2. Dinliyor durumuna geçince kare değişiyor mu; konuşma bitince boşta klibine dönüyor mu?
  3. Varsayılan kapalıyken boşta sürükle; bırakınca konum değişti mi?
  4. Jarvis'i kapatıp aç; pencere aynı konumda ve aynı boyutta açıldı mı?
  5. Varsayılan kapalıyken boşta sürükleme ve sağ tık menüsü her durumda çalışıyor mu? **Boşta tıklamayı geçir** açık + yeniden başlatmada boştaki tıklama alttaki pencereye geçiyor mu (maskot tepki vermiyor mu)?
  6. Maskotu ikinci monitöre taşı; pencere tamamen o monitörde kaldı mı, ekran dışına taşmadı mı?
  7. Sağ tık: Gizle / Konum sıfırla / Çık beklendiği gibi çalışıyor mu?
  8. DPI %150 veya %200 iken pencere keskin ve doğru boyutta mı?
- **Tam doğrulama:** `python -X utf8 -m modules.validation` **exit 0**, çıktı "Tüm test grupları başarılı."; Python ve Node grupları OK. Bu düzeltme **10 test** ekledi (mascot 19→26, nxapi +3); toplam test sayısı bu koşunun özet çıktısında ayrıca basılmadı.
- **Dürüst sınır:** Bu PR'da pencere canlı açılmadı; CPU ≤ %2, gerçek iki-pencere tıklama testi, gerçek sürükleme, ikinci monitör ve DPI davranışı **ölçülmedi**. Oynatıcı Tk iş parçacığında çalışır; monitörler arası DPI değişimi açılışta bir kez okunur, taşıma sırasında yeniden ölçeklenmez. Tıklama geçişi stil bitleri ve ayar kapıları test edildi; gerçek fare olayıyla iki pencere testi yapılmadı.
