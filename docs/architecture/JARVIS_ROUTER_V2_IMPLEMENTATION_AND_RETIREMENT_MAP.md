# Router V2 — uygulama ve emeklilik haritası

14 Kasım2026; kullanıcı `JARVIS_ROUTER_ARCHITECTURE_V2.md` belgesini son karar olarak yeniden verdi ve sistemi kurmayı istedi. Taban main `a872bdf8c490a6ba00ca23e103fba3bd73544603`; açık PR yok. Tek uygulama dalı `gpt/router-single-closeout-20261114`; ikinci Router/Scheduler/GoalState kurulmaz.

İki yaklaşım değerlendirildi: bağımsız servis/gateway veya mevcut sahipleri evrimleştirmek. Kullanıcı V2 belgesi ikinciyi açıkça seçer; mevcut typed Router, llm, user_models, usage_meter ve SQLite kota sahibine göç yapılır. Önceki GPT-OSS-ana/vision-yalnız-Ollama önerileri hedef değildir. Model kimliklerinin kesin rol kabulü canlı ölçümdür; kod/test PASS o ölçüm sayılmaz.

| Dikiş | Mevcut sahibi | Hedef bağlantı ve emeklilik |
|---|---|---|
| Profil/owner/request/deadline/validator | smart_router, llm, brain_model_understanding, requests_state | Kapalı profil ve veri kapsamı; aynı exact model, tek en çok2-deneme ve request trace; smart_router.run / prompt task_type / direct repair son caller taşındığında kaldırılır. |
| Gemini veri politikası | provider_privacy, privacy_sources, mevcut owner router settings | Training koşulları doğru kalır; sohbet/seçilmiş içerik kapsamı owner kurulum ayarında açık ve geri alınabilir. PUBLIC provenansı değiştirilmez; local/gizli egress korunur. |
| Görüntü | llm.ask_image, model_capabilities | Aynı typed vision request; doğrulanmış Gemini vision + uygunsa hazır yerel yedek; metin modele görüntü gönderilmez. |
| Usage/kota/health | usage_meter, router_quota | Aynı mevcut SQLite üzerinde account/project/model-group scope; request trace, null bilinmeyen usage, gerçek finish/truncation; request/eşzamanlılık ve opt-in doğrulanmış token politikası; yeni scheduler yok. |
| Özel API/rol | user_models, paid_providers, web_models, webui | Protokol/model/owner-secret ve rol bağlantıları; save/test ayrı. Hazır OpenAI/Claude vendor enum/kart/seçici kaldırılır; eski anahtarlar custom disabled kayda korunarak göçer. Ücretli custom'a otomatik free fallback yok. |
| UI/alan sözleşmeleri | AGENTS ve alan notları, yol haritası/ledger | Sabit hazır profiller + ayrı özel API alanı; seçilen ana/yedek ve ret nedenleri; kod/canlı kabul ayrımı ve güncel sahiplik. |

Kabul: önce ağsız negatif davranışlar; gerçek kayıt/dosya/SQLite/Core/Bridge seams ve yalnız provider/cihaz sınırı fake. Exact-source tam validation + Ruff/ArchitectureGuard + roadmap kapıları; tek PR sonrası repo bekleme kuralı. Sonuç için kullanıcı açıkça bakınca WindowsCI/gerçekPC okunur. Canlı model rol seçimi, Brain≥95/sıfır kritik yanlış işlem, gerçek vision, token/neuron/hesap limitleri ve p50/p95 ölçülmeden kapandı denmez. Model/hesap bilgisi yokken quota/billing garantisi uydurulmaz.

## Uygulanan kullanıcı akışı

Hazır kapalı profiller `brain_understanding`, `conversation`, `public_research`, `long_worker`, `vision`, `local_only`, `custom_explicit` olarak çağırandan gelir; istem metni sınıflandırılmaz. Gemini konuşma/seçilmiş içerik izinleri aktif owner kurulumunda ayrı açılır, geri alınabilir; Google ücretsiz içeriği eğitim/ürün geliştirmede kullanabilir. PRIVATE içerik PUBLIC diye yeniden etiketlenmez. Görüntü gerçek Gemini image-parts taşıyıcısına veya yeterliliği doğrulanmış yerel modele gider. Ollama yeteneği `/api/show` üzerinden açık kontrolle beş dakikalık gözlemdir; LM Studio/llama.cpp için doğrulanmamış vision iddiası açılmaz. Model indirilmez.

21 Kasım 2026 hazır bağlantı kararı. Ayarlar › Yapay Zekâ’da Gemini, Groq ve Cloudflare sabit rollerini kullanır. Kullanıcı API anahtarını kaydeder. Cloudflare hesap kimliği ister. Gemini veri izinleri ayrı kaydedilir. Bağlantıyı dene, seçilen sağlayıcıya kişisel içeriksiz tek küçük istek gönderir. Kart gerçek yanıtı veya ret nedenini, Otomatik Model Seçimi son sohbeti yanıtlayan sağlayıcı ve modeli gösterir. Özel API, kendi modelini, rolünü, çağrı sınırını ve isteğe bağlı harcama sınırını taşır.

Hazır sağlayıcılar için ücretsiz plan beyanı, proje/kota grubu, günlük çağrı ve sohbet payı ayarları kaldırıldı. Gerçek sağlayıcı kota ve hız sınırları görünür, sabit yedek sırası korunur. Gözlemlenen reset bilgisi aynı anahtara bağlanır. Mevcut SQLite Özel API sınırlarını, gerçek kullanım bilgilerini ve tanı izini saklar. Kullanım bildirilmiyorsa null kalır.

Sağlık exact bağlantı/anahtar/model, kesin auth'ta bağlantı ve bilinen429 kapsamındaki proje bazındadır. Şema reddi, yerel deadline, iptal ve görüntü özellik uyuşmazlığı sağlıklı metin sağlayıcısını genel beklemeye sokmaz. Kaynak claim'i mevcut Core LeaseTable/OS claim sahibindedir; model_wait süresi bitse bile gerçek taşıyıcı kapanana kadar tutulur. Router yeni Scheduler/queue/Brain kurmaz. Çağıranın interactive/background sınıfı mevcut request bağlamında taşınır. Native model seçimi kadar owner bağlamı da plan/taşıma öncesinde doğrulanır ve ContextVar tokenıyla geri yüklenir.

`_LAST[owner]` kaldırıldı; SQLite owner/request/call/attempt izleri politika, ana/yedek, gerçek model, atlama, durum/finish, rezervasyon ve gerçek kullanımı ayrı gösterir. Prompt, cevap ve anahtar tutulmaz. Streaming uygulanmış gibi gösterilmez; ilk-token ölçülmediyse null'dır. Kısmi structured çıktı Core etkisi olamaz.

## Emeklilik ve dört kapanış koşulu

| Dikiş | Sözleşme | Eski göçü | Kullanıcı bağlantısı | Emeklilik |
|---|---|---|---|---|
| Model seçimi/repair | Typed ModelRequest → RoutePlan → exact adapter, en çok2 fiziksel deneme | Brain/sohbet/araştırma/worker/vision taşındı | Mevcut model_wait/Brain/Web akışları | `smart_router.run`, `task_type`, `_with_models`, `ollama_model_for`, `_ollama_task`, özel yerel retry yok |
| Gemini/görüntü | Owner-scoped veri izni + doğrulanmış özellik | Public-only/local-only varsayımları izin kapılarına taşındı | Kurulum tercihleri, gerçek image-parts, yerel yetenek kontrolü | Eski direct `_ask_image` yolu yok |
| Özel API | Owner secret/endpoint/revision/protokol/rol | Eski vendor metadata/secret disabled korunur | Gerçek Bridge CRUD/model listesi/açık tek test/form | `_PAID`, sabit vendor enum/kart/adapter ve eski ücretli seçici kaldırıldı |
| Kullanım/kota | Aynı ledger, shared scope, null unknown, kaynak payı | Sayaç ve request trace genişledi | Ayarlar/istek izleri/mevcut runtime beklemesi | `_LAST`, ayrı model dolaşımı/genel provider cezası otoritesi yok |

Bağlantı denemesi seçilen modelin o çağrıya gerçek yanıt verdiğini ölçer. Brain exact-model semantik ölçümü ayrı tanı akışıdır. Manuel `brain_output_diagnose_holdout.py --run` hazır adayla, `--qualify-local` veya `--qualify-connection ID --accept-paid` seçilen adayla ölçer. CI gerçek model çağırmaz.

## Resmî kaynak ve model kararı

14 Kasım2026 incelemesi, canlı hesap/model kalite sonucu değildir:

- Gemini3.5 Flash Lite image input/context kartı: https://ai.google.dev/gemini-api/docs/models/gemini-3.5-flash-lite ; ücretsiz/ücretli ve eğitim koşulları: https://ai.google.dev/gemini-api/docs/pricing ve https://ai.google.dev/gemini-api/terms . Native schema/tool desteği taşıyıcıda doğrulanmadığı için ilan edilmez.
- Groq model/ücretsiz plan/gerçek hesap limitleri: https://console.groq.com/docs/models , https://console.groq.com/docs/rate-limits , https://console.groq.com/docs/billing-faqs . GPT-OSS120B/20B veya Qwen boyutu Brain kabulü sayılmaz.
- Eski Cloudflare Llama3.1 FP8 için20 Kasım kapanış takvimi: https://developers.cloudflare.com/changelog/post/2026-11-05-planned-model-deprecations/ . Güncel incelenmiş metin adayı `@cf/google/gemma-4-26b-a4b-it`: https://developers.cloudflare.com/workers-ai/models/gemma-4-26b-a4b-it/ . Taşıyıcımız yalnız metin; kartta vision olması Cloudflare adapter'a vision kazandırmaz.
- Cloudflare Workers Free günlük10000 neuron ve Paid plan farkı: https://developers.cloudflare.com/workers-ai/platform/pricing/ . Bu sayı uygulamada uydurma token bakiyesine çevrilmez. Ücretsiz plan beyanı gerçek hesap API doğrulaması değildir.

Bu kaynaklara bağlı kanıtlar zaman sınırlıdır. Model kimlikleri runtime rol kabulünden önce kesin kalite tercihi sayılmaz; yeni/popüler model otomatik ana model yapılmaz. NVIDIA/Nemotron normal havuzda dışarıdadır; deney başlatılmadı.

## Doğrulama ve açık kabul

Ağsız davranış testleri gerçek request/Core/owner dosyası/SQLite/Bridge ile; yalnız sağlayıcı ve donanım sınırları fake olarak yürür. Yeni ve göçen testler owner bağlamı geri yükleme, paralel istek izi, aynı proje son-slot yarışı, foreground payı, geç yanıt/claim, revocation/key rotation, secret snapshot, truncation, iki-deneme, ücretli pin, göç ve protokol payload'larını kapsar. Tam exact-source validation ve guard sonucu PR açıklamasında kayıtlanır.

Açık kalan kabul: aynı source SHA için Windows CI/gerçekPC; gerçek ücretsiz hesap limitleri, model bazında Türkçe/vision doğruluğu ve p50/p95/first-token; Brain canlı rol raporu; gerekirse doğrulanmış tokenizer/pricing/neuron dönüşümü. Bu işler ölçülmeden Router/Brain ürün fazı tamamlandı diye işaretlenmez. Bir PR yayımlandıktan sonra mevcut `pr-test-bekleme.md` kuralı uygulanır.

Özel API vision için ek ölçüm dikişi: açık tek sentetik PNG çağrısında yalnız piksellerdeki8 haneli kodun doğru okunması; exact owner/endpoint/protokol/model/key/revision ve taşıyıcı source-fingerprint'e bağlı7 günlük native vision gözlemi üretir. Kod prompt'a konulmaz, challenge/yanıt depolanmaz, bağlantı etkinleştirilmez. Metin bağlantı testi veya checkbox yerine gerçek görüntü taşıma kanıtıdır; genel vision/Brain kalite kabulü sayılmaz. Bağlantı/secret/taşıyıcı değişimi gözlemi iptal eder. Normal kaydetme/açılış bu testi başlatmaz.

Geliştirme sırasında main'e #630/#631 ses/Brain kontrol düzeltmeleri birleşti; Router dalı bunların `b3e3993c53ee375a26f6e5048b4a3e4db50e6c6e` tabanına taşınır. Açık #632 bağımsız ses işidir; devralınmaz. Son doğrulama bu birleşik kaynak üzerinde yapılır.


### #633 Windows CI düzeltmesi —14 Kasım2026

`ca9b02b` Windows koşumu [43613281563](https://github.com/hamdkose-ctrl/Jarvis-v2/actions/runs/43613281563) PASS değildir:6460 testte446 error/11 failure/7 skip. Birincil hata, SQLite `with connection` bloğunun commit/rollback yapıp handle'ı kapatmamasıydı; trace/rol kabulü/usage uzlaştırmasının tüm çıkışları `closing` ile açıkça kapanır. `reserve` kendi `finally: close` sahibini korur. Bağlantıları güçlü referansla bellekte tutan5 regresyon eski kodda5FAIL verdi; commit/rollback, erken dönüş, hata ve gerçek persist davranışı korunarak kapatma doğrulandı. Windows klasör temizliği gevşetilmez; GC/retry ile açık handle saklanmaz.

Kalan11 failure, kurulu yerel model varken test sırasıyla yerelde yeniden üretildi. Bir fake sağlayıcı hatası `_HEALTH` kaydını diğer testlere bırakıyor, haber planlayıcısını gereksiz modelsiz kurtarmaya sokuyordu. Hata fixture'ı kendi Router store/health ve internet gözlemine ayrıldı; doğrudan typed planı gerçekten iki fiziksel fake denemeyle sınar. Aynı sıra/kurulu model koşulu düzeltmeden sonra31PASS, ilgili39 test PASS verdi. Disabled özel bağlantı testi var olan yerel rotanın korunmasını doğrular; makinede Ollama bulunmamasını şart koşmaz. Haber politikası, gerçek model sağlık beklemesi ve Core yetkisi değiştirilmedi.

Bu takipte birleşen #632 mevcut kod olarak entegre edildi; yalnız roadmap append çakışmasında iki taraf da korundu. Son kaynak tam validation'dan tekrar geçer; yeni Windows CI/gerçekPC ve canlı model/vision kabulü hâlâ ayrı kapıdır.


## Güncel PC haber kabulü takibi — 14 Kasım 2026

`d2d6cf24ff1e` Windows CI [43615464802](https://github.com/hamdkose-ctrl/Jarvis-v2/actions/runs/43615464802) geçti. [Aynı SHA gerçek PC raporu](https://github.com/hamdkose-ctrl/Jarvis-v2/pull/633#issuecomment-6880915713) validation ve yerel model UI/inference için passed; haber kabulünün üç senaryosu için "Haber hedefi oluşturulmadı" nedeniyle failed'dır. Bu, güncel PC raporu yok anlatımının yerini alır.

Kabul betiğinin Brain'siz eski `hedef` girişi emekliye ayrıldı. Yerine owner/RID-bound gerçek typed Router/envelope validator/prepare/handoff/Core zinciri bağlandı. Anlamlandırma aday planı ve adapter yanıtı yalnız bu sabit senaryolar için prepare süresince fixture'dır; geçici Router store/health kullanır ve Core yürütmesi başlamadan kaldırılır. Aşağı-akış model taşıyıcıları kapalı/sayılan kalır. Canlı kaynak, tarih, iki yayıncı ve dosyanın kendi kanıtı/verify/kapalı-hedef değişmezliği şartları korunur. Rapor fixture'ı açıklar; canlı Brain kalite/hesap/rol veya çalışan Scheduler kabulü saymaz.

Kabulün açığa çıkardığı kapalı-hedef devam sorunu da sınırlı State status yoluyla giderildi: son terminal hedefin kimliği gözlenir, diğer pending/açık iş varsa turu devralmaz, Core aynı owner/kimlik/terminal durumunu yeniden doğrular ve hiçbir worker/mutasyon açmadan mevcut kapalı-hedef yanıtını verir. Eski ham metin hedef yaratma yetkisi geri getirilmedi. Üç kaynak-taklitli gerçek Core sohbet/dosya senaryosu düzeltme öncesi failed, düzeltme sonrası geçti; eksik ikinci yayıncı ve değişmiş hedef negatifleri korunur. Yeni exact-source validation/Windows/gerçek PC kabulü ayrı kaydedilir.


Canonical kabul girişinin mimari envanteri de aynı değişiklikte göçer: doğrudan `runtime.handle` için eski acceptance istisnası tamamen kaldırılır; `prepare`/`handoff` kapıları yalnız `acceptance_checks.py` için açık `--news`/sabit semantic fixture/senkron source gerekçesiyle kaydedilir. Statik tarama kapsamı ve eşitlik kontrolleri korunur; yeni başka bir kapı yine başarısız olur.


## İkinci gerçek PC takibi ve #634 tabanı — 14 Kasım 2026

`fd03dbabcc1a` için [Windows CI43619940254](https://github.com/hamdkose-ctrl/Jarvis-v2/actions/runs/43619940254) başarılıdır. [Gerçek PC raporu](https://github.com/hamdkose-ctrl/Jarvis-v2/pull/633#issuecomment-6881316586) validation/yerel model/desktop passed, haber failed: üç senaryo hedef/dosya kontrollerinden sonra terminal devam mesajında kaldı; dış keşifte 6 adaydan doğrulanmış kaynak yoktu. Bekleyen bir gerçek profil olgusu ile aynı devam hatası yeniden üretildi. Kabulün yalnız Goal store'u değil değişebilir Profile/history/Task/desktop/filesend/request sahipleri de geçici alana ayrıldı; owner kimliği ve gerçek gizlilik ayarları korunur. Başka gerçek işe devam edilmez veya pending silinmez; kayıtlı kullanıcı profil/task/desktop dosyalarının değişmezliği sınanır. Üretim State önceliğine yeni bypass eklenmedi.

Genel haber `araştır` fiili `_fold` ile `araştir` oluyordu; aynı normalizasyon uygulanmamış stop-word sözlüğü bu fiili konu sayıyor, araştırma sözcüğü içermeyen geçerli haberleri eliyordu. Sözcük/sözlük aynı şekilde katlanır; gerçek konunun, AI/coğrafyanın, yayın zamanının ve makale kimliğinin koşulları korunur. Katalog dışı gerçek parser/pipeline yolu kaynak taşıyıcısı taklidiyle sınanır; ek model/sağlayıcı/okuma bütçesi yoktur. Geliştirme ortamından üç bilinen PC adayına üretim HTTPS erişimi connection refused verdi; bu yoklama Windows canlı kabulü değildir.

Bağımsız ses kuyruğu #634 `a3bd8e5` tabanı normal merge ile alındı. `requests_state.py` çatışmasında Router `request_identity` ve sesin `execution_seconds`/iptal-fence/`request_state` davranışları birlikte korundu; roadmap'in iki tarafı saklandı. Yeni exact-source tam validation, Windows ve gerçek PC kabulü ayrı kaydedilir.


## Groq HTTP413 istek kapasitesi — 15 Kasım 2026

Gerçek Windows rol ölçüm raporunda Groq tek Brain isteğini 8000 TPM kapasitesine karşı 10479 istenen token gerekçesiyle reddettiği bildirilmiştir; bunlar o yanıtın sayılarıdır, başka hesap/model için sabit limit değildir. Kaynakta HTTP413 genel `Groq yanıt vermedi`/unknown hatasına dönüşüyor, normal sağlık beklemesi sonraki küçük çağrıları da etkiliyordu. Native adapter artık tipli `ProviderRequestLimitError` üretir: gerçek HTTP durumu ve varsa kapalı TPM türü/sayısal Limit/Requested bilgisi korunur, ham sağlayıcı gövdesi ve organizasyon/key/mesaj bilgisi taşınmaz. Bilinmeyen null; mevcut request/token/usage rezervasyonu veya resmî model politikası uydurulmaz.

RoutePlan'ın bu istekte kapasite reddi aldığı exact aday bir daha gönderilmez; validator için üretilmiş aynı-model repair kopyası da ağsız atlanır. Bu hata health/rate-limit beklemesi yazmaz, küçük sonraki istek çalışabilir; zaten uygun yedek kalan toplam≤2 fiziksel denemede kullanılabilir. 429/daily/auth, mevcut owner/privacy/paid kapıları ve iptal/deadline davranışı korunur. Brain yalnız bir hata kodu taşır; Core MODEL_UNAVAILABLE içinde güvenli kapasite açıklaması/failed feedback verir, yürütme yetkisi üretmez. Full tanısı provider_request_too_large/unmeasured olur; sınıf/Corpus/kalite eşikleri ve mevcut30sn/2048 bütçeleri değişmez.

Native HTTP sınırı taklit edilerek gerçek Router/SQLite/LLM/Brain/Full ve Core handoff yolları sınanır: aynı büyük girdi tek gönderim, uygun yedek yalnız kalan bütçe, sonraki küçük aynı-model çağrı, gizli gövde sızıntısı yok, bilinmeyen sayılar null, Full ilk yanıtsız örnekte ölçülemedi ve sıfır effect. Bu kod kanıtı canlı Groq/Gemini rol kabulü değildir. Ayrı BRAIN-11 #639 operatör işi devralınmaz; bu dar Router hata davranışı tek PR'dadır.
