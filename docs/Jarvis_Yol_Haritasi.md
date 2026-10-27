# Jarvis Yol Haritası — Hasat Listesi Yapım Sırası

Tarih: 25 Ekim 2026 · Hamdi · Durum güncellemesi: 26 Ekim 2026 (main 5cae9b9, "bitti" kuralına göre yeniden değerlendirildi)

## "Bitti" kuralı

Bir madde ya da faz ancak şu dört koşulun **hepsi** sağlanınca "tamamlandı" sayılır:

1. **Sözleşme:** Sözleşme / arayüz yazıldı.
2. **Göç:** Eski kod göçü tamamlandı; eski mantık yeni yapıya taşındı.
3. **Bağlantı:** Yeni kod kullanıcı akışına bağlandı; Jarvis çalışırken gerçekten devreye giriyor (yalnız testten çağrılması yetmez).
4. **Temizlik:** Eski kod / legacy kısım kaldırıldı.

Dördünden biri eksikse faz "kısmi" kalır ve sıradaki faz onun üstüne kurulmaz. PR merge edilmiş olması tek başına "bitti" demek değildir. Eski kod yoksa (tamamen yeni yetenek) 2. ve 4. koşul "yok, gerekmiyor" diye açıkça yazılır; yalnız belge PR'larında koşul 3 ve 4 uygulanmaz.

İşaretler: ✅ dört koşul da tamam · 🟡 merge edildi ama koşullardan biri eksik (eksik olan yazılı) · 🔄 açık PR var, merge bekliyor · işaretsiz: başlanmadı.

Kısa gösterim: `[1✓ 2✗ 3✗ 4✗]` = sözleşme var, göç / bağlantı / temizlik yok. `–` = o koşul uygulanmaz (taşınacak ya da silinecek eski kod yok), `🟡` = yarım.

Bu sayfa, Hasat Listesi'nin Jarvis-v2 main (028e2fc) durumuna göre eksik kalan işlerini yapım sırasıyla verir. Bitmiş şeyler yazılmadı. Her maddede ne eklenecek ve şu an ne var yazıyor. Ücretli ya da kart isteyen hiçbir şey listede yok. Her faz bir öncekinin kabul kanıtını ister.

---

## Karar bekleyenler

**Şu an sizden bekleyen karar yok.**

Alınmış kararlar: Faz 9 bölünmesi onaylı, anahtar havuzu yok, MCP/API sunucusu yok, ses tanıma yok, Telegram ve WhatsApp kalıyor, "ben Hasan" profilleri kısıtsız. GoalState RFC'nin dört kararı da kabul edilmiş, Faz 0'da kalan iş kodlama.

---

## Genel sıra

- Faz 0: Aşama 0–4 kapanışı (🟡 kısmi: canonical işlerde eski JSON yazımı durdu (#385), eski işler legacy'de; 2 madde başlanmadı)
- Faz 1: 429 ve Ollama'sız çalışma (🟡 kısmi: eski hata yolları duruyor, iş PC'sinde kabul bekliyor)
- Faz 2: Zamanlama, olay, hook ve temel muhakeme (🟡 kısmi: canlı akışa bağlandı, ikinci hook sistemi duruyor)
- Faz 3: Envanter ve Finance sözleşmesi (🟡 kısmi: Finance sözleşmesi var, 3-B..3-F göçü yapılmadı)
- Faz 4: Yalnız okuma yapan worker'lar (🟡 kısmi: 7/7 sözleşme merge edildi, hiçbiri akışa bağlı değil)
- Faz 5: Güvenilirlik ve gözlem
- Faz 6: Sandbox, skill, kod ajanı
- Faz 7: Alt-ajan ve Kanban
- Faz 8: MCP istemcisi ve güvenli eklenti
- Faz 9: Bilgisayar kontrolü
- Faz 10: Dışarıya etki eden işler
- Faz 11: Profiller, hafıza, context
- Faz 12: Düşük öncelikli alanlar

---

## Faz 0 — Aşama 0–4 kapanışı

**Durum: 🟡 kısmi `[1✓ 2🟡 3✓ 4✗]`. 4 PR merge edildi (#347, #348, #349, #385) ama hiçbir madde dört koşulu birden sağlamıyor: eski işler hâlâ legacy `goal_executor` JSON'unda yürüyor; kaydetme kancası (`goal_state_save_hook.py`) canonical işlerde eski JSON'u artık yazmıyor (#385), legacy-authority işlerde yazmaya devam ediyor. Başlanmadı: PC watcher kabulü, üç Guard kuralı.**

Mimari borç ödenir: canonical GoalState geçişi tamamlanır, eski JSON yazımı durdurulur, Guard kuralları kod içine işlenir. Bu bitmeden sonraki hiçbir faz sağlam temele oturmuyor.

Bu faz bitmeden yeni mimari genişleme açılmaz.

- 🟡 (#349) `[1✓ 2🟡 3✓ 4✗]` Eski `goal_executor` kaydı canonical GoalState'e küçük adımlarla taşınacak: yeni işler doğrudan canonical yetkiyle açılacak, eski işler bitene kadar legacy kalacak. Kaydetme kancası canonical işlerde yalnız canonical senkron ve ExecutionRecord yazıyor (#385); legacy-authority işlerde eski JSON'u da yazıyor.
- 🟡 (#385) `[1✓ 2🟡 3✓ 4✗]` Eski JSON yazımı durdurulacak. Canonical-authority işlerde durduruldu; legacy-authority işler eski yazımı sürdürüyor, eski `<id>.json` dosyaları diskte duruyor. RFC'nin dört kararı da kabul edilmiş (sabit `agent` modu, authority işareti, geri doldurma politikası, terminal koruması), kalan iş kodlama.
- 🔄 Faz 0 promotion PR'ı açık bekliyor: operatör onaylı, fingerprint'e bağlı promotion legacy payload'ını önce ExecutionRecord'a taşır; canonical authority değişimi başarısızsa ExecutionRecord geri alınır. Eski `<id>.json` silinmez veya değiştirilmez; yalnız promotion sonrası gelecekteki legacy yazımı durur. Kabul/merge bekleniyor, bu yüzden Faz 0 hâlâ 🟡.
- 🟡 (#348) `[1✓ 2🟡 3✓ 4✗]` Eksik canonical kayıt için operatör onaylı geri doldurma akışı cutover'a bağlanacak. Fonksiyon ve testi var, akışa bağlı değil.
- 🟡 (#347) `[1✓ 2✓ 3✓ 4✗]` Canonical tarafın "bitti" bilgisi eski tarafa iletilecek. Bugün canonical bitmiş işi yeniden açmıyor ama eski taraf bunu öğrenmiyor. Eski tarafa iletim çalışıyor; eski kayıt kaldırılınca bu köprü de kalkacak.
- Gerçek PC watcher kabul kaydı main'in kendi SHA'sı için alınacak ve Aşama 0–4 kapanışı tek belgeyle ilan edilecek. Windows CI main'de yeşil, watcher kayıtları şimdilik yalnız PR bazlı.
- Üç kural kodda zorlanacak: Domain invariant ve Decision Authority, her etkinin makbuz üretmesi, cron / oturum / hafızanın GoalState yerine geçmemesi. Üçü de şu an yalnız belgede yazılı, Guard denetlemiyor.

---

## Faz 1 — 429 ve Ollama'sız çalışma

**Durum: 🔄 kısmi `[1✓ 2✓ 3✓ 4🔄]`. Provider sınıflandırma temizliği açık: `model_health.py` içindeki ayrı 401/403/429 ayrımı ve `image_gen.py` içindeki bağımsız HTTP/429 ayrımı ortak `failure_policy.classify` hattına taşınıyor; eski kopyalar kaldırılıyor. CI + gerçek PC watcher kabulü gelmeden bu temizlik tamamlandı sayılmaz. İş PC'sinde Ollama'sız gerçek kabul ve gerçek LM Studio / Groq denemesi ayrıca bekliyor.**

Ağ ve model hataları net biçimde yönetilir; Ollama yoksa ya da kota doluysa asistan yine çalışır. İstikrar yoksa zamanlama veya worker eklemek anlamsız.

- 🟡 (#350) `[1✓ 2✓ 3✓ 4✗]` 429, kota, ağ, kimlik doğrulama ve yerel model yokluğu kullanıcıya ayrı ve anlaşılır nedenlerle gösterilecek; kalıcı kota hatası geçici hatadan ayrılacak. Şu an hata sınıflandırması ve bekleme var, ama bazı hedeflerde ham hata gidiyor.
- ✅ (#350) `[1✓ 2✓ 3✓ 4✓]` Sınırlı yeniden deneme ve artan bekleme (backoff) eklenecek. Şu an bekleme var, backoff yok.
- 🟡 (#352) `[1✓ 2✓ 3✓ 4–]` Ollama kurulu değilken modelsiz kısmın doğrulanmış teslimi haber ve finans dışındaki hedeflere de yayılacak. Haber ve finans için modelsiz yol var. İş PC'sinde gerçek kabul gerekiyor; kabul gelmeden ✅ yazılmaz.
- ✅ (#352) `[1✓ 2– 3✓ 4–]` LM Studio ve llama.cpp için yerel uç nokta ayarı eklenecek (opsiyonel). Şu an yalnız Ollama var.
- ✅ (#351) `[1✓ 2✓ 3✓ 4✓]` Kullanıcı başına model seçimi Gemini dışına, yani Groq ve yerel modele genişleyecek; kullanım sınırı gözlemi eklenecek. Şu an yalnız Gemini seçilebiliyor, sayaç karakter bazlı.
- ✅ (#351) `[1✓ 2– 3✓ 4–]` Ücretli sağlayıcıya otomatik geçiş yapılmaz.

---

## Faz 2 — Zamanlama, olay, hook ve temel muhakeme

**Durum: 🟡 kısmi. İlk PR'lar (#353–#371) incelemede (incelemeler/faz2_inceleme.md) canlı akışa bağlı çıkmamıştı; #374 bağladı, #380 kaynak takibine abonelik ekledi, #382 webhook tekrar korumasını ekledi, hepsi merge edildi. #377 kapatıldı (sohbet cron komutları #374 ile girdi). Ölü `modules/proactive.py` silindi. Eksik temizlik: `gateway_hooks.py` hâlâ `hooks.py`'den ayrı ikinci bir hook sistemi ve üretim kodunda hiçbir yerden çağrılmıyor; `shell_hooks.py` de çağrılmıyor (sandbox'a kadar stub, bilerek).**

Cron zamanlama, olay aboneliği ve hook altyapısı eklenir. Aynı fazda temel muhakeme de gelir: artı/eksi analizi, dürüst eleştiri, rehberlik ve proaktif öneri. Otomasyon ile düşünen yanıt aynı temele oturduğu için worker'lardan önce buraya düşerler.

- ✅ (#374) `[1✓ 2✓ 3✓ 4✓]` Genel zamanlanmış görev gelecek: cron ifadesi, "şimdi çalıştır", modelsiz betik görevi, her çalıştırmada temiz oturum. Şu an doğal dil zamanı ve kuyruk var, cron ve "şimdi çalıştır" yok.
- ✅ (#374, #380) `[1✓ 2✓ 3✓ 4✓]` RuntimeEvent için kalıcı abonelik kurulacak: kaynak izleyici, olay, tazelik süzgeci, GoalState kanıtı. Şema ve commit hattı var, gerçek üretici yok (Guard uyarısı ARCH-W001).
- ✅ (#374, #382) `[1✓ 2✓ 3✓ 4✓]` Webhook ve olay tetikleri WhatsApp dışına genişleyecek, sonuç birden fazla kanala gidecek. Şu an yalnız WhatsApp webhook'u ve ntfy var.
- 🟡 (#374) `[1✓ 2– 3✓ 4✗]` Hook sistemi eklenecek: ajan, araç, model, onay, oturum, alt-ajan ve Kanban hook'ları ile yürütmeyi değiştiremeyen gözlemci hook'ları. Şu an hiç yok. Bağlı, ama `gateway_hooks.py` ikinci sistem olarak duruyor (koşul 4).
- ✅ (#374) `[1✓ 2– 3✓ 4–]` Araç öncesi ihlalde işlemi durduran (fail-closed) ortak kapı eklenecek, mevcut `runtime_execution_gate` üstüne.
- 🟡 (#353) `[1✓ 2– 3✗ 4✗]` Gateway olay hook'ları ve shell hook'ları sandbox'tan sonra eklenecek. Stub var ama hiçbir yerden çağrılmıyor; gateway tarafı `hooks.py` üstüne indirilip ayrı sistem silinmeli.
- ✅ (#354, #370, #374) `[1✓ 2– 3✓ 4–]` Artı/eksi analizi eklenecek: önemli bir karar veya seçenek söz konusu olduğunda Jarvis seçeneklerin artılarını ve eksilerini sıralayıp gerekçeli öneride bulunacak. Şu an doğrudan cevap veriliyor, yapılandırılmış değerlendirme yok.
- ✅ (#355, #374) `[1✓ 2– 3✓ 4–]` Dürüst eleştiri eklenecek: iş ve hayat konularında "burada şu zayıf çünkü…" denilebilecek; yumuşatma olmadan ama kırıcı olmadan. Şu an yalnız haftalık hedef raporunda (Goals.java) kısmi eleştiri var, genel konuşmada yok.
- ✅ (#357, #374) `[1✓ 2– 3✓ 4–]` Rehberlik ve tavsiye eklenecek: adım adım pratik yol gösterme, hangi seçeneği neden tercih etmeli, risk ve dikkat noktası bildirimi. Şu an Hoca öğrenme tarafında var, genel danışmanlık yok.
- ✅ (#358, #374) `[1✓ 2– 3✓ 4✓]` Proaktif öneri eklenecek (varsayılan açık): ilgili bir konu veya risk görülünce "bunu da düşünebilirsin" ya da "burada dikkat et" diyecek; ayardan kapatılabilir. Şu an yalnız açık takip isteğiyle (monitor) tetikleniyor, genel konuşmada yok.

---

## Faz 3 — Envanter ve Finance sözleşmesi

**Durum: 🟡 kısmi. Envanter belgesi (#360) ✅. Finance yalnız koşul 1'de: `finance_domain.py` ve sözleşme belgesi var ama üretim kodunda hiçbir yerden çağrılmıyor, eski finans mantığı hâlâ `watcher` ve `domain_tools` içinde. 3-B..3-F göç adımları (#362'deki tablo) yapılmadan Finance bitmiş sayılmaz.**

Finance ve envanter ayrı domain sözleşmelerine bağlanır. Worker'ların okuyacağı veri alanları temizlenmeden worker'lar başlayamaz.

- 🟡 (#362) `[1✓ 2✗ 3✗ 4✗]` Finance ayrı domain olarak sözleşmeye bağlanacak: veri, alarm, analiz, kaynak doğrulama dalları ve kod göçü planı. Karar belgesi var, kod hâlâ iletişim tarafında. Salt okuma, para hareketi yok.
  - 3-B `watcher._finance_price` → `finance.quote` (başlanmadı)
  - 3-C `watcher.finance_tick` ve yardımcıları → `finance_alert_tick.py` (başlanmadı)
  - 3-D alarm teslimi Communication'da, ntfy başlığı ayrılır (başlanmadı)
  - 3-E `domain_tools.exchange` → `finance.dated_rate` (başlanmadı)
  - 3-F `domain_tools.csv_analysis` finans kolu → `finance_analysis.csv_summary` (başlanmadı)
- ✅ (#360) `[1✓ belge PR'ı]` 705 maddelik envanter repoya Capability Intake ikinci dalga olarak işlenecek ve Hermes sürüm referansı commit SHA'ya sabitlenecek. Şu an ilk dalga 20 aday var. Yalnız belge PR'ı.

---

## Faz 4 — Yalnız okuma yapan worker'lar

**Durum: 🟡 kısmi `[1✓ 2✗ 3✗ 4✗]`. 4A–4G'nin hepsi merge edildi (#372, #373, #375, #376, #378, #381, #384) ama her PR yalnız yeni bir modül ve testinden oluşuyor. Yedi modülün (`research_providers`, `file_worker_extensions`, `browser_readonly`, `drive_readonly`, `finance_readonly`, `gmail_calendar_readonly`, `computer_worker_contract`) hiçbiri üretim kodundan çağrılmıyor; eski yollar (ör. `finance.py`, `tool_finance.py`, mevcut tarayıcı ve Gmail okuma kodu) olduğu gibi çalışıyor. Sıradaki iş yeni harf açmak değil, her harfi aynı sırayla (4A→4G) göç, bağlantı ve temizlikle kapatmak.**

Salt okuma yapan worker'lar sırayla devreye girer: araştırma, dosya, tarayıcı, Drive, finans, Gmail/Takvim ve PC Worker sözleşmesi. Veri sözleşmesi hazır; yalnız okuma en güvenli başlangıç noktasıdır.

Araştırma zinciri bu sırayla kurulur: arama sağlayıcısı, kaynak sıralama, paralel araştırma, web ve dosyayı birlikte kullanan araştırma, Hoca araştırma döngüsü, konudan sapma kontrolü.

**Sıra kilitli:** Faz bölünmez ama PR sırası kesindir. "Merge edildi" yetmez; bir harf "bitti" kuralının dört koşulunu sağlamadan sonraki faz (Faz 5) açılmaz. Aynı anda tek alan açık olur; bir sonraki harf, önceki harf merge edilmeden başlamaz. Sıra: 4A Araştırma ve Hoca, 4B FileWorker sağlamlaştırma, 4C Tarayıcı salt okuma, 4D Drive salt okuma, 4E Finans salt okuma, 4F Gmail ve Takvim salt okuma genişlemesi, 4G PC Worker temel sözleşmesi.

### 4A — Araştırma ve Hoca

🟡 (#372) `[1✓ 2✗ 3✗ 4✗]` Sözleşme modülü ve testi var; akışa bağlı değil.

- Kart istemeyen arama sağlayıcıları eklenecek: SearXNG, DuckDuckGo, Tavily, Exa, Firecrawl. Arama ile içerik çıkarma ayrı sağlayıcılar olacak. Şu an yalnız doğrudan yayıncı okuma var.
- arXiv ve akademik makale araştırması, kaynaklar arası çelişki karşılaştırması ve kaynak sıralama eklenecek. Şu an hiçbiri yok.
- RSS ve site izleyicisi tam kapsamlı olacak; haftalık haber otomasyonu ve uzun araştırmada bağlam yönetimi eklenecek. Şu an RSS dar, haftalık otomasyon zayıf.
- Kaynak gösterimi biçimi ve konudan kopmama denetimi Hoca dışına yayılacak. Şu an kısmen Hoca'da var.

#### Ek kabul kriterleri — Fable/Claude agent benchmark

- **Kısmen uygulandı (PR #424): güncellik isteğini doğru yönlendirme.**
  - **Kod kanıtı:** `modules/freshness.py:fresh_request` tek karar noktası; router (`_fresh_research_request`) ve `work_modes` (`fresh_external`) buradan beslenir. Tanım kalıbı ("nedir/ne demek/tarihçe") artık yalnız açık tazelik işareti yoksa statik der; `mevcut` ve `bugunku` tazelik işaretleri eklendi. Kararı kilitleyen test: `tests/test_freshness_rule.py::test_explicit_freshness_wins_over_definition_pattern` ve `tests/test_quota_routing.py::test_explicit_freshness_beats_definition_phrasing`.
  - **Beklenen davranış:** "bugün/son/güncel/mevcut/şu an" gibi açık tazelik işareti + konu ("kur/dolar/haber/...") varsa sorgu taze kaynağa (`intent=task`) yönlener; tazelik işareti olmayan sade tanım ("Dolar nedir?", "NVIDIA nedir?") statik/chat kalır ve gereksiz web aramasına zorlanmaz. Kanıtlandı: `Bugünkü dolar kuru nedir?`→task, `Güncel altın fiyatı nedir?`→task; `Dolar nedir?`→chat.
  - **Kabul testi:** Aynı konu için bir güncel ve bir durağan sorgu `test_explicit_freshness_wins_over_definition_pattern` ile assert ediliyor (güncel → taze route, durağan → chat, ağ çağrısı yok).
  - **Kalan:** "kural" gibi değişken-bilgi konuları freshness konu listesinde henüz yok; taze kaynak aramasının canlı kanıtı (gerçek yayıncı okuması) bu PR kapsamında ölçülmedi — routing kararı ve statik/taze ayrımı birim düzeyinde doğrulandı.
- **Tespit edildi — uygulama bekliyor: kaynak çelişkisinde ek doğrulama.**
  - **Kod kanıtı:** Uygulama PR'ında kaynak sıralama/karşılaştırma yolunun çelişkiyi algıladığında ek bir doğrulama adımı çalıştırdığı ve sonucu evidence zincirine eklediği gösterilecek.
  - **Beklenen davranış:** Güvenilir iki kaynak aynı olgu için çelişirse Jarvis ilk sonucu sessizce seçmeyecek; ek kaynak veya birincil kaynakla doğrulama yapacak, çözülemeyen çelişkiyi açık bırakacak.
  - **Kabul testi:** Enjekte edilmiş iki çelişkili kaynakla araştırma çalıştırıldığında ek doğrulama çağrısı veya "çelişki çözülemedi" sonucu zorunlu olacak; ilk kaynak doğrudan nihai gerçek kabul edilmeyecek.

### 4B — FileWorker sağlamlaştırma

🟡 (#373) `[1✓ 2✗ 3✗ 4✗]` Sözleşme modülü ve testi var; akışa bağlı değil.

- Belgeden yapılacak iş, yükümlülük ve son tarih çıkarma eklenecek. Mailden tarihli iş ve ödev parçalama var, genel belge için yok.
- PPTX üretimi, genel dosya yaması ve dosya arama komutu eklenecek. PPTX okuma var, yama yok, arama bilgi tabanıyla sınırlı.
- Dosya güvenliği tamamlanacak: özel dosya türleri (FIFO vb.) koruması, büyük ve minified dosya sınırı, Unicode dosya adı testleri. Boyut sınırı ve yalıtılmış PDF okuma var.

### 4C — Tarayıcı salt okuma

🟡 (#375) `[1✓ 2✗ 3✗ 4✗]` Sözleşme modülü ve testi var; akışa bağlı değil.

- Tarayıcıya erişilebilirlik ağacı tam hâle gelecek; birden çok sekme, indirme ve yükleme, diyalog yönetimi eklenecek. Şu an tek sayfa ve sade okuma var.
- Kayıtlı oturum koruma, kendi şifreli yerel kimlik kasası ve 2FA için insana devretme eklenecek. Ayrı profil ve elle giriş betiği var, kasa yok. Kimlik bilgisi asla modele gitmez.
- Chrome DevTools Protokolü ve gerçek tarayıcı profiline bağlanma eklenecek, görüntü destekli yedek yolla. Şu an yok.

### 4D — Drive salt okuma

🟡 (#376) `[1✓ 2✗ 3✗ 4✗]` Sözleşme modülü ve testi var; akışa bağlı değil.

- Google Drive, Docs ve Sheets okuma entegrasyonu eklenecek. Gmail ve Takvim var, Drive yok.

### 4E — Finans salt okuma

🟡 (#378) `[1✓ 2✗ 3✗ 4✗]` Sözleşme modülü ve testi var; akışa bağlı değil.

- 🟡 F-002 PR 1: doğrulanmış fiyat, kaynak kanıtı, freshness ve en az iki OHLCV mumu varsa mevcut Finance worker üzerinden salt-okunur yapılandırılmış giriş/stop/hedef taslağı üretilir. Seviye yöntemi yalnız son iki mumun gözlenen aralığıdır; veri eksik veya stale ise plan `incomplete` döner ve sayı uydurmaz. Pozisyon boyutu, PASS/BLOCK, kullanıcı onayı, broker ve emir yürütme kapsam dışıdır. PR kabulü bekleniyor; Faz 4E hâlâ 🟡.

- Günlük fiyat serisi (OHLCV), hisse karşılaştırma ve veri tazelik kontrolü tüm kaynaklara yayılacak. Kaynaklar yalnız TCMB, Frankfurter, CoinGecko Demo, BtcTurk ve yedekli Yahoo. Şu an anlık fiyat var, seri yok.
- Portföy analizi, risk ve varsayım açıklaması, finans kanıt paketi, ticker arama, DCF, benzer şirket ve LBO becerileri ve finans araştırma ajanı eklenecek. Şu an izleme listesi ve alarm var. Yatırım tavsiyesi verilmez.

### 4F — Gmail ve Takvim salt okuma genişlemesi

🟡 (#381) `[1✓ 2✗ 3✗ 4✗]` Sözleşme modülü ve testi var; akışa bağlı değil.

- Gmail konuşma (thread) okuma ve Takvim planlama önerisi genişleyecek. Şu an okuma ve arama var.

#### Planlama saat gösterimi

- Google Takvimden gelen saatli kayıt, plan çıktısında Jarvis'in çalıştığı makinenin saat dilimine ikinci kez çevrilmez; kaynağın takvim duvar saati korunur. Bu yalnız salt-okunur gösterim/eşsizleştirme düzeltmesidir; Google takvim yazımı, yetki veya etkinin kapsamı değişmez. Kanıt: PR #413; test `test_google_event_keeps_calendar_wall_time`.

### 4G — PC Worker temel sözleşmesi (yalnız Core tarafı)

🟡 (#384) `[1✓ 2✗ 3✗ 4✗]` Sözleşme modülü ve testi var; akışa bağlı değil.

- ComputerWorker sınırı tanımlanacak, UIA temel ölçümü ve yetenek / makbuz sözleşmesi yazılacak. 4F merge edildikten sonra açılır. Hesap Makinesi ve Not Defteri pilotu, uygulama izin listesi ve manifest var.

Sınır: FileWorker salt okunurdur. Tek dosya değişikliği `file_ops` işidir, toplu değişiklik PC Worker ile Core'un etki hattından geçer. `desktop_agent` ve `desktop_uia` UIA temeli olarak kalır, genişletilmez. Tarayıcı işi BrowserWorker'ındır.

---

## Faz 5 — Güvenilirlik ve gözlem

**Durum: başlanmadı.**

İzleme kimliği, maliyet ölçümü ve değerlendirme eklenir. Worker'lar aktif; neyin çalıştığını ölçmeden ilerlemek kör uçuştur.

- Ortak izleme kimliği ve ana / alt iş izi gelecek; LLM, araç, onay, API ve oturum izleri tek şemada toplanacak. Şu an istek kimliği, kullanım sayacı ve izin kaydı ayrı ayrı duruyor.
- Gerçek token ve maliyet ölçümü, önbellek isabeti, gecikme ve araç çağrısı sayısı eklenecek. Şu an karakter bazlı sayaç ve ses gecikmesi var.
- OpenTelemetry ve Langfuse benzeri dışa aktarım gelecek, yalnız kendi kurulumunuzda, gizlilik korumalı (opsiyonel). Şu an yok.
- Değerlendirme eklenecek: aynı senaryoyu tekrar koşturma, A/B worker karşılaştırması, hareket kaydı, düşmanca dosya testi, PII duman testi, sağlığın tek ekranda toplanması. JarvisBench v0 ve geniş test seti var.
- Makbuz ve kanıt kapsama oranı ile gerçek ajan benchmark raporu eklenecek. Manifest tablosu var, oran raporu yok.

---

## Faz 6 — Sandbox, skill, kod ajanı

**Durum: başlanmadı.**

Sandbox, skill sistemi ve kod ajanı devreye girer. Kod çalıştırmak ve skill yüklemek izole ortam gerektirdiğinden önceki fazlar hazır olmadan buraya gelinmez.

Bu fazın tüm araçları parolayla korunan geliştirici menüsünün arkasında olur.

- Yalıtılmış çalıştırma ortamı eklenecek: görev ve worker başına ayrı alan, kaynak ve süreç sınırı, ağ çıkışı denetimi, yetki düşürme, temizlik. Önce yerel yalıtım. Şu an yalnız adayı yalıtılmış kopyada derleyip test etme var.
- Gerçek anahtarı sandbox'tan gizleyen kimlik bilgisi vekili ve opak belirteç eklenecek. Şu an yok.
- Docker, SSH ve Singularity arka uçları, riskli betiği gerçek PC'den ayırma ve sandbox sağlık kontrolü eklenecek. Şu an yok.
- Tehlikeli komut tespiti ve yıkıcı komut onayı tüm çalıştırma yollarında ortak olacak; gözetimsiz modda her şey reddedilecek. Şu an onaylı program çalıştırma ve yıkıcı eylem sınıfı yalnız araç tarafında var.
- Skill sistemi eklenecek: oluştur, listele, göster, kur, güncelle, sil; yalnız gerektiğinde bağlama yükleme; betik ve şablon dosyaları; agentskills uyumu. Şu an hiç yok. Önce salt okuma pilotu.
- Skill güvenliği eklenecek: sürüm sabitleme, kaynak kaydı, onay ve fark gösterimi, prompt-injection, veri sızdırma, yıkıcı komut ve tedarik zinciri taraması, işletim sistemi uyumu.
- Harici skill depoları doğrudan alınmayacak, yalnız uyarlanacak; başlangıçta yalnız sizin skill'leriniz çalışacak. Jarvis skill kataloğu ve yetenek eksiğinde skill arama ile insan onaylı kurma eklenecek. Şu an yetenek keşfi ve onaylı araç kaydı var.
- Kullanıcı düzeltmesinden ve başarılı iş akışından skill üretme eklenecek, insan onaylı. Şu an düzeltmeden kural öğrenme var.
- Kod ajanı hattı eklenecek: genel terminal, arka plan süreç yöneticisi, test-önce iş akışı, hata ayıklama ve kod inceleme becerileri, inceleyici ajan. Şu an geliştirici modu (taslak, test, geri alma) ve onaylı program çalıştırma var.
- Codex ve OpenCode worker olarak bağlanacak, yalnız ücretsiz kipte: OpenCode varsayılan yerel Ollama modeliyle, isteğe bağlı ücretsiz modellerle veya ücretsiz Gemini / Groq anahtarıyla; Codex yalnız yerel kipte (`codex --oss`). Paralel kodlama için ayrı çalışma alanı gelecek. Şu an Jarvis'te yok. Claude Code Jarvis'in içinde kullanılmaz.
- CI takibi, issue iş akışı, bağımlılık incelemesi, depo bağlam dosyaları ve git diff bağlamı eklenecek; kod eylemi makbuzları tamamlanacak. Şu an PR açma ve yerel çalışma ağacı yayını var.

---

## Faz 7 — Alt-ajan ve Kanban

**Durum: başlanmadı.**

Alt-ajan yaşam döngüsü ve Kanban panosu eklenir. Sandbox hazır; paralel iş ancak güvenli ortamda dağıtılabilir.

- Alt-ajan yaşam döngüsü tamamlanacak: yalıtılmış bağlam, çalışanları listeleme, yönlendirme, durdurma, iptal, iş ve token bütçesi, eşzamanlılık ve derinlik sınırı. Şu an kalıcı görev grafı, paralel çalıştırma ve iptal var; yönlendirme ve derinlik sınırı yok.
- Yapılandırılmış alt-ajan çıktısı eklenecek: JSON şema sözleşmesi, bozuk çıktıda sınırlı düzeltme, kısmi / yarıda kalan / bütçesi biten / bilinmeyen sonucun ayrı gösterimi. Şu an tek tip sonuç var.
- Görev ve alt-ajan bazlı araç kısıtı ile devir sözleşmesi eklenecek. Şu an uzman tanımlarında kısıt var.
- Alt-ajan başına terminal, model ve profil yönlendirmesi ile takılabilir delegation arka ucu eklenecek; yalnız kendi makinelerinize. Sandbox'tan sonra.
- Kanban panosu eklenecek: görev oluşturma, sahiplenme, tamamlama, nedenli engelleme, insan engel kaldırma, bağımlılık, ana / alt görev, ek dosya. Şu an kuyruk, bağımlılık ve kalp atışı var, pano yok. Core Job'ın yerine geçmez, yalnız görünümdür.
- Kanban inceleme akışı eklenecek: inceleyici atama, değişiklik isteme, inceleme tamamlama, olay hook'ları, çok ajanlı iş dağıtımı.

---

## Faz 8 — MCP istemcisi ve güvenli eklenti

**Durum: 🟡 kısmi. Kamera/WebRTC cihaz bridge adapter'ı mevcut web Bridge yüzeyine bağlı; uzak kamera karesi artık mevcut Vision/`observe(camera)` analiz yoluna da bağlanıyor. Gerçek cihaz kabulü ve gerçek WebRTC signaling tamamlanmadan bu iş ✅ sayılmaz.**

MCP istemcisi ve güvenli eklenti sistemi eklenir. Kendi altyapımız sabit; dış araçlara ancak o zaman güvenle kapı açılır.

- 🟡 Kamera/WebRTC cihaz köprüsü: yalnız observation/evidence kaynağı; yerel stop uzaktan yeniden açılamaz, en fazla 3 viewer, WebRTC/JPEG frame sınırı, owner izolasyonu ve ephemeral retention var. Goal/Vision observation bağlantısı yapıldı; gerçek cihaz kabulü ve gerçek WebRTC signaling bekliyor.
- Sabit, salt okuma MCP istemcisi eklenecek: dinamik araç keşfi, sunucu bağlantıları, MCP olay istemcisi, yerel MCP bağlantıları. Sandbox'tan sonra. Şu an yalnız referans kataloğu var.
- A2A ve harici ajan servislerine bağlanma en sona kalır.
- Güvenli eklenti sistemi sıfırdan yazılacak: araç, yaşam döngüsü hook'ı, komut, paketlenmiş skill, katalog, katman, commit'e sabitli sürüm, onay, işletim sistemi uyumu. Şu an eski `plugins.py` kullanıcı Python'unu doğrudan yüklüyor; o büyütülmeyecek.
- Sağlayıcı eklentileri eklenecek: model, hafıza, context motoru, bilgisayar kontrolü, yerel TTS, yerel STT, delegation, gateway.
- Araç setleri eklenecek: birleşik, özel ve platforma özel setler, araç bazında aç / kapat, iş akışı kapılı araçlar, araç arama. Şu an merkezi araç kaydı ve izin politikası var.
- Bağlantı katmanı eklenecek: kendi bağlayıcılarımız, adlandırılmış hesaplar, hesap yeniden adlandırma, bağlayıcı onay ekranı, aynı uygulamada çoklu hesap, kimlik bilgisi yalıtımı. Şu an kullanıcıya özel belirteç ve servis yapılandırması var.

---

## Faz 9 — Bilgisayar kontrolü

**Durum: başlanmadı.**

Core tarafı bilgisayar kontrol sözleşmesini tamamlar; fare ve klavye tarafı C# PC Worker'ın işidir. Tüm temel altyapı hazır olmadan fiziksel kontrol eklenmez.

Onaylı bölünme: Jarvis-v2 yalnız Core tarafını yapar (yetenek manifesti, izin ve etki politikası, WorkerResult sınırı, makbuz, IPC sözleşmesi, salt okuma benchmark). Fare, klavye ve C# kısmı ayrı PC Worker'ın işidir (mimari belge §16).

**Core tarafı (Jarvis-v2):**

- IPC sözleşmesi kodlanacak: yalnız yerel ve aynı kullanıcı (ACL'li named pipe veya stdio, ağ portu yok), sürüm uzlaşması ve `CONTRACT_MISMATCH`, komut / iptal / iptal onayı. Şu an yalnız mimari belgede tanım var.
- Girdi modu ve lease eklenecek: `uia_pattern` (odak ve imleç çalmaz, pencere lease'i, kullanıcı aynı anda çalışabilir) ve `physical_input` (masaüstü geneli lease, kullanıcı girdisinde durur). Worker modu kendiliğinden yükseltmez. Şu an yok.
- PC capability'leri manifeste satır satır girecek (`pc.window.control`, `pc.input.click`, `pc.input.type` vb.), her birinin izin sınıfı, onay kuralı ve makbuz türüyle. Şu an tek `goal.desktop` satırı var.
- Hedef sınıfları Core politikasına yazılacak: Jarvis penceresi ve uzak erişim yasak; terminal, kod editörü, tarayıcı ve şifre yöneticisi açık ama her eylemde ayrı onay ve makbuz ister, şifre alanı okunmaz. Yönetici yetkili hedefte Worker kendini yükseltmez, ayrı capability ve her seferinde onay ister.
- Site ve köken bazlı izin listesi tarayıcı dışı akışlara yayılacak. Şu an tarayıcı alan adı kapısı var.
- Acil durdurma: tek komutla çalışan PC işini iptal etme ve lease'i bırakma. Şu an genel iptal var, PC'ye özel yok.

**PC Worker tarafı:**

- Gerçek Windows PC'de CUA arka ucu UIA temeline karşı ölçülecek; yetmezse C# Windows-native yedek gelecek. Arka planda, imleç ve odağı çalmadan çalışma, kaydırma ve sürükleme eklenecek. Şu an Hesap Makinesi ve Not Defteri pilotu var, genel girdi yok.
- Genel tıklama, yazma, kaydırma, sürükleme, klavye kısayolu, pencere ve uygulama hedefleme ve yönetici yetkili uygulamalar için ayrı güvenli yol eklenecek. Şu an kontrol çağrısı (Invoke / Value) var.
- Görüntü tabanlı yedek, ajan imleci, kullanıcı ve ajanın eşzamanlı çalışması ve her PC eyleminde makbuz eklenecek. Şu an sonuç geri okuma var, makbuz tam değil.
- Yerel Windows uygulama kontrolü Hesap Makinesi ve Not Defteri dışına PC Worker üzerinden çıkacak. Şu an uygulama izin listesi var.
- macOS ve Linux arka uç adayları değerlendirilecek (düşük öncelik).

---

## Faz 10 — Dışarıya etki eden işler

**Durum: başlanmadı.**

Telegram/WhatsApp, Gmail ve Takvim gibi dışarıya etkili yazma işlemleri eksiksiz tamamlanır. Salt okuma yolları hazır; yazma her adımda makbuz ve doğrulama ister.

Her yazma işlemi kesin hedef, niyet kaydı, makbuz ve okuyup doğrulama ister.

- Telegram ve WhatsApp için ortak mesajlaşma ağ geçidi eklenecek: adaptör arayüzü, eşleştirme, kimlik doğrulama, gelen oturum yönlendirme, sağlık izleme, güncelleme sonrası toparlanma. İkisi de telefondan yazmak için kalır; aynı tek Jarvis oturumudur. Şu an tek tek gönderim adaptörleri ve WhatsApp webhook'u var.
- Telegram gelen mesaj ve DM işlemleri tamamlanacak; platforma özel araç seti eklenecek. Şu an giden mesaj ve bot güncelleme alıcısı var.
- Gmail'e yanıt, taslak, arşivleme, çöpe atma ve etiketleme eklenecek; gönderim sonrası okuyup doğrulama ve teslim makbuzu tamamlanacak. Şu an gönderim var, okuma geniş.
- Takvime etkinlik oluşturma ve güncelleme, takvimden hatırlatma, mailden görev çıkarma ve mailden GoalState'e devir eklenecek. Şu an takvim yalnız okuma, mailden tarihli iş çıkarma var.
- Birden fazla Google hesabı ve iş / kişisel ayrımı için hesap soyutlaması eklenecek. Şu an kullanıcıya özel tek belirteç var, Outlook ayrı.

---

## Faz 11 — Profiller, hafıza, context

**Durum: 🔄 kısmi — #421 Physical Object Memory açık PR; CI/watcher kabulü bekleniyor. Fazın geri kalan maddeleri başlanmadı.**

Kullanıcı profilleri, uzun dönem hafıza, context sıkıştırma ve kendini geliştirme eklenir. Tüm yetenekler çalışıyor; kişisel uyarlama ve büyüme bunların üstüne oturur.

- 🔄 (#421) `[1✓ 2– 3✓ 4–]` Physical Object Memory: kamera/Vision gözlemi `Observation -> CandidateFact -> kullanıcı onayı -> durable object memory` hattından geçer. Aday kayıtlar relevance prompt'a girmez; onaylı kayıt mevcut `facts` + relevance gate hattına bağlanır. Provenance tutulur, manuel düzeltme sonraki model taramasıyla ezilmez, bir taramada görülmeyen nesne silinmez (`location_unknown`), nesne/QR/etiket metni untrusted evidence olarak kalır. Güncel head için CI + gerçek PC watcher PASS gelmeden tamamlandı sayılmaz.

### Ek kabul kriterleri — Fable/Claude agent benchmark

- **Tespit edildi — uygulama bekliyor: öğrenilmiş kurallar Core ve izin politikasını geçersiz kılamaz.**
  - **Kod kanıtı:** İlk uygulama PR'ı learned-rule/memory uygulama noktasında açık precedence kontrolü göstermeli; öğrenilmiş kural yalnız advisory/context girdisi olabilir ve Domain invariant → Decision Authority → JIT Permission → Effect Policy sırasının sonucunu değiştirememelidir.
  - **Beklenen davranış:** Daha önce öğrenilmiş bir tercih veya kural "bunu otomatik yap", "bu alıcıyı kullan" ya da "onay isteme" dese bile Core hedefi, izin sınıfını veya kullanıcı onayı gereksinimini değiştiremez.
  - **Kabul testi:** Öğrenilmiş kuralın hedef/alıcıyı değiştirmeye veya gerekli onayı atlamaya çalıştığı senaryoda execution kararı değişmeden kalmalı ve işlem mevcut Core/Permission politikası uyarınca reddedilmeli ya da onay istemelidir.
- **Tespit edildi — uygulama bekliyor: ilgisiz hafızayı bağlama almama (memory relevance gate).**
  - **Kod kanıtı:** Uygulama PR'ında hafıza adaylarının bağlama girmeden önce görevle ilgililik filtresinden geçtiği ve filtre sonucunun testle kilitlendiği gösterilecek.
  - **Beklenen davranış:** Hafıza yalnız mevcut sorunun sonucunu, önerisini veya gerekli bağlamını gerçekten değiştiriyorsa kullanılacak; alakasız geçmiş ayrıntılar yalnız "hatırlıyorum" göstermek için prompt/context'e eklenmeyecek.
  - **Kabul testi:** Aynı kullanıcı için biri görevle ilgili, biri ilgisiz iki hafıza verildiğinde yalnız ilgili olanın oluşturulan bağlama girdiği; ilgisiz olanın model girdisine taşınmadığı kanıtlanacak.

- Kullanıcı profilleri eklenecek. Jarvis tek örnek, tek oturum, tek arayüz kalır. Asıl kullanıcı Hamdi. Biri "ben Hasan" derse (sesle ya da yazarak) Jarvis Hasan'a göre çalışır; Hasan'ın kendi ayrı hafızası ve geçmişi olur. Kısıtlama yoktur, her profil her özelliği kullanır. Geliştirici menüsü şifresi olduğu gibi kalır. Şu an owner alanı ve kullanıcıya özel belirteç var, sözle profil geçişi yok.
- Oturum arama, çapraz oturum hatırlama, oturum üst-alt ilişkisi, oturum meta verisi, geçmiş arama ve hafıza ön yükleme eklenecek. Şu an kalıcı sohbet geçmişi var, arama yok.
- Hafıza sağlayıcı arayüzü eklenecek, yalnız kendi sunucunuzdaki Mem0 ve Honcho ile; hafıza yaşam döngüsü hook'ları gelecek ve hafızaya yazmadan önce gizli bilgi temizliği yazım yoluna bağlanacak. Şu an yerel profil ve kural hafızası var, maskeleme yazım yoluna bağlı değil.
- Proje ve ortam hafızası Hoca dışına yayılacak; konuşma hafızası ile GoalState ayrımı koda yazılacak. Şu an Hoca oturum hafızası var.
- Kendini geliştirme dilimi eklenecek: iz yakalama, iyileştirme adayı, tekrar üreten test, taslak PR, skill ve prompt evrimi. İnsan onaylı, kendi kendine merge yok, geliştirici menüsünde. Şu an kural öğrenme ve onay bekleyen öneri var.
- Context sıkıştırma eklenecek: token farkında, bekleme süreli, başarısızlıkta yedek yol, taşma toparlama, karar ve yapıt koruma. Şu an hiç yok.
- `@dosya`, `@klasör`, `@git-diff` ve `@URL` bağlam referansları ile bağlam dosyaları eklenecek. Şu an yok.

---

## Faz 12 — Düşük öncelikli alanlar

**Durum: başlanmadı.**

Medya düzenleme, ses sağlayıcısı, yedekleme, akıllı ev ve toplu işleme gibi istenen ama acil olmayan alanlar tamamlanır. Temel sağlamsa buraya gelir.

- Yerel çalışan medya becerileri eklenecek: görsel düzenleme, video analizi, HTML'den video, ComfyUI, Manim, ASCII video, p5.js, web tasarım, şarkı sözü, metin insansılaştırma. Şu an görsel üretim, sahne montajı ve FFmpeg video var.
- Ses ve görsel sağlayıcı soyutlaması eklenecek: yerel Piper, Kokoro, XTTS, whisper.cpp ve yerel komut tabanlı TTS / ASR. Şu an edge-tts, Piper / SAPI ve faster-whisper doğrudan bağlı.
- Yönetim ekranları tamamlanacak: ağ geçidi, skill, eklenti, bağlantılar, günlükler, sağlık, kullanım, oturum ve zamanlama ekranı, masaüstü proje bağlamı, kenar çubuğuna sabitleme. Şu an ana, sohbet, dosya, görüntü, harita, uygulama ve ayarlar sayfaları var.
- Yedekleme ve taşıma eklenecek: ayar, hafıza, skill, oturum, profil ve tam yedek; kimlik bilgisiz tek profil dışa aktarma; PC'den PC'ye taşıma; başka ajan sisteminden içe aktarma (OpenClaw dahil). Şu an yalnız güncelleme öncesi yerel yedek var.
- Kararlı sürüm kanalı, sürüm sabitleme ve bağımlılık sağlığı tamamlanacak; bozuk kurulum kurtarma, çalışma klasörü eksik tespiti ve kurulum / taşıma sihirbazı eklenecek. Şu an güvenli güncelleme, geri alma ve bağımlılık kilidi var.
- Home Assistant, akıllı ev ve IoT, Spotify dışı müzik denetimi ve yazıcı dışındaki cihaz kontrolü eklenecek. Şu an yazıcı (OctoPrint / Moonraker), Spotify ve onaylı cihaz kaydı var.
- Toplu işleme (binlerce girdi) ve kendi makinenizdeki uzak worker eklenecek; eksik yetenekte kullanıcıya açıklama ve kurma onayı ile. Şu an tek makine kuyruğu ve yetenek keşfi var.

---

## Listede olmayanlar

**Ücretli veya kart isteyen:** Brave, Perplexity, Parallel, xAI, X (Twitter) ve X API, Modal, Daytona, Mem0 / Honcho / Supermemory bulut sürümleri, bulut worker, Alpha Vantage, prompt önbellekleme ve araç ağ geçidi, bulut video ve görsel üretimi, ses klonlama hizmetleri, yapay zekâ sunucu avatarı, ücretli şifre yöneticileri ve ücretli yönetilen bağlayıcı hizmetleri.

**Karar gereği çıkarılanlar:** anahtar havuzu, Jarvis'i MCP veya API sunucusu yapmak, IDE istemcisi, ses tanıma, uzak PC ve çoklu oturum, çoklu arayüz.

**İstenmeyen alanlar:** Notion, Obsidian, Box, Airtable; algılanmayan tarayıcılar (Camofox gibi); uzman grup sohbeti ve `@bahsetme`; Telegram ve WhatsApp dışındaki mesajlaşma platformları; worker / eklenti pazarı.

---

## Ortak kurallar

- **"Bitti" kuralı:** Bir faz ya da madde ancak dört koşulun hepsi sağlanınca bitmiş sayılır: (1) sözleşme / arayüz yazıldı, (2) eski kod göçü tamamlandı, (3) yeni kod kullanıcı akışına bağlandı, (4) eski kod / legacy kısım kaldırıldı. Her PR açıklaması hangi koşulları kapattığını yazar; durum güncellemesi bu dört koşula göre yapılır, PR sayısına göre değil.
- Her faz ayrı dalda, küçük PR'larla ilerler; AGENTS.md'ye göre önce plan ve iki seçenek, sonra sizin onayınız.
- Dış kod alınmadan önce lisans, Windows uyumu, güvenlik ve Core sözleşmesi kontrol edilir.
- Hiçbir yetenek ikinci bir Core kurmaz.
- Ajan çalışma akışı: ajan yalnızca PR açar → PR Hamdi'nin bilgisayarında açık kalır ve test edilir → Hamdi "kontrol et" deyene kadar ajan bekler → onaylanırsa ajan merge eder → bir sonraki işe geçmeden önce Hamdi'ye sorar.

---

## Referans noktaları

- **hermes-agent** (MIT) — 705 maddelik hasat listesinin çıktığı kaynak. Doğrudan alınabilecekler: `skills/` talimat dosyaları, `todo_tool.py`, `memory_tool.py`, `session_search_tool.py`. Bağlantı: https://github.com/nousresearch/hermes-agent