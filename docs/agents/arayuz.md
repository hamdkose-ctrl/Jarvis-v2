# BRAIN-10 sonuç görünürlüğü — 14 Kasım 2026

Ekip merkezinin query projection'ı mevcut Core result_presentation servisini kullanır: kontrol edilen done adım, artifact ve receipt gösterilir; değişmiş/eksik/yanlış owner kanıtı unavailable/incomplete görünür. Projection özgün journal'ı değiştirmez. Butonların terminal kararı ve control fingerprint'i özgün record_state/kayıttan gelir; yalnız görünüm eksildi diye kapanmış task'a continue/stop önerilmez. İncomplete işler dikkat sayacına ve açık ayrıntıya dahil edilir. Kanıtı kontrol et butonu aynı Core/query sahibine gider; UI verifier, worker veya ikinci GoalState değildir.

---

# BRAIN-09 Hafıza tercihleri — 14 Kasım 2026

Hafıza ekranında sunumun9 kapalı tercihi mevcut Profile sahibine `pref_set` ile yazılır. Etkin değerin açık/öğrenilmiş/default kaynağı gösterilir; açık seçim kaldırılır veya learned öneri ayrı silinir. Bridge Core persona servisini çağırır; UI anlam/izin kararı üretmez. Render response owner ile snapshot owner'ı eşleştirir; select/button event'i de güncel owner'ı tekrar kontrol eder. Geç eski kullanıcı cevabı/yazımı yeni kullanıcıya uygulanmaz. Alan notu: `docs/agents/persona.md`.

---

# Masaüstü arayüzü — 21 Kasım 2026

- Tek masaüstü girişi /nx.html. Sol menü Ana ekran, Sohbet, Dosyalar, Ekran ve PC, Ekip Merkezi, Çalışma, Günlük işler ve Ayarlar sayfalarını doğrudan açar. Yetenek haritası Ayarlar'dan erişilir. Daha önce tarayıcıya kaydedilen geçersiz bir sayfa ana ekrana çözülür.
- Ana ekranda mevcut gönderme, ekleme, mikrofon ve ses sahipleri çalışır. Sağ panel yalnız etkin kullanıcının team_snapshot kayıtlarını ve yerel takvimde bugüne ait etkinlikleri gösterir. Gerçek durum yokken örnek veya yüzde gösterilmez. Bekleme durumu var olan /events akışından okunur.
- Ekip Merkezi seçili çalışmanın adımlarını yanında gösterir. İptal, devam, soru ve onay mevcut team_control ve aynı Core kimliğini kullanır. Form taslağı yalnız aynı işlemin kontrol imzası korunurken yenilemede saklanır. Kullanıcı değişince eski sonuçlar gösterilmez. Uzman, kaynak, kuyruk ve doğrulama araçları mevcut sözleşmelerle çalışır.
- Teslim indirme, team_artifact üzerinden seçili işin etkin kullanıcıya ait kabul edilmiş adımını yeniden okur. Kanıt, benzersiz dosya adı, izinli kök ve okunan baytların özeti eşleşmesi gerekir. En çok 16 MB. İndirme sonucu işin durumunu değiştirmez.
- Hologram, dekoratif animasyon, eski Menü sahnesi ve arka plan taşıyıcıları kaldırıldı. Masaüstünün varsayılanı koyu lacivert temadır. Kayıtlı açık, koyu ve sistem tercihleri geçerlidir. Bakır ana düğmeleri ve seçili öğeleri vurgular. Ana ekranda cam halkalar, Dosyalar ve teslim başlıklarında cam belge görseli kullanılır. Görseller statik ve yereldir. Küçük Jarvis ve tepsi simgesi aynı işareti kullanır. Kullanıcının eski özel arka plan dosyası silinmez.
- Dosyalar sayfasında arama ve liste solda, seçili dosya ve işlemleri sağdadır. `file_preview` etkin kullanıcıyı ve mevcut dosya köklerini denetler. İlk PDF sayfası mevcut PDFium okuyucusunda, desteklenen görseller Pillow ile yerelde küçültülerek çizilir. En çok 20 MB kaynak okunur. Yanıt yalnız istek sahibi ve seçili dosya hâlâ eşleşiyorsa gösterilir.
- Ayarlar: tek sayfa, mevcut form ve araç sahipleri. Sol bölüm seçimi, Ayarlarda ara, sağlayıcı kartları, ses, hesap, gizlilik ve GitHub işlemleri korunur. Gönderme, pencere ve onay kontrolleri mevcut yerel /api köprüsünü kullanır.
- Paylaşım, Ekran ve PC sayfasından veya ortak yazı çubuğunun seçeneklerinden açıkça seçilir. Ekran sayfası kendi önizlemesini gösterir, diğer sayfalarda mevcut yerel köşe önizlemesi kullanılır. Kamera ve Windows işlemleri gerçek cihazdan ayrıca doğrulanır.
- Motorun user, assistant ve step olayları aynı istek kimliğiyle sohbete bağlanır. Telefon kullanıcı verisi farklı PC profiline gösterilmez. Yetkisiz HTTP, yerel oturum ve istek gövde sınırları mevcut web.py sahiplerindedir.

## Router V2 bağlantı alanı —14 Kasım2026

Yapay Zekâ alanı hazır Gemini/Groq/Cloudflare/isteğe bağlı yerel profilleri ve ayrı Özel API formunu sunar. Hazır rol sırası kullanıcı priority editörü değildir; ek API'ye Brain/sohbet/araştırma/uzun iş/vision rolü verilir. Hazır OpenAI/Claude kartları ve eski paid activation eylemleri emeklidir; generic protokol seçenekleri vendor seçimi değildir. Eski kayıtlar kapalı custom olarak görünür, key formda gösterilmez. Kaydetme/açılış inference yapmaz; tek test ayrıca açık tercihtir ve ücretsiz/rol kabulü sayılmaz.

Gemini konuşma/seçilmiş içerik izinleri ayrı ve geri alınabilir; eğitim koşulu açıkça yazılır. Ücretsiz hesap bakım düğmesi kullanıcı beyanıdır, provider bakiye kontrolü değildir. Uygulama günlük/paralel/foreground payı ve ortak proje scope alanları resmî quota diye etiketlenmez. Custom free pool checkbox kanıt olmadan adayı açmaz. İsteğe bağlı parasal tavan, maliyet üst sınırı bilinmediğinde çağrıyı engeller. Yerel vision kontrolü yalnız runtime yetenek metadata'sı okur, model indirmez.

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
