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

Ayarlar › Yapay Zekâ hazır profilleri ve ayrı Özel API alanını gösterir. İlave bağlantı exact model/protokol/rol/veri izniyle kaydedilir. OpenAI-compatible Chat Completions, Responses ve Anthropic Messages protokolleri vardır; sabit ücretli vendor kartı/seçimi yoktur. Eski anahtarlar silinmeden **disabled** custom kayda göçer. Kaydetme/açılış model çağırmaz. Tek bağlantı denemesi açık seçimle en çok32 çıktı tokenı isteyen bir çağrıdır; ücretsiz hesap/rol yeterliliği kanıtı değildir. Ücretli rol kendi bağlantısına bağlı kalır; ücretsiz havuz ücretliye düşmez. Custom `free` etiketi havuz kanıtı değildir: ayrıca owner/endpoint/key-fingerprint/exact-model/veri koşulu kanıtı ve açık havuza katıl seçimi gerekir. İncelenmiş custom ücretsiz hesap kataloğu başlangıçta boştur.

Mevcut SQLite `requests` tablosu account/project/key scope ve deneme kimliğiyle genişler; ikinci sayaç yoktur. Cloudflare hesabı, aynı anahtarı paylaşan modeller ve açık ortak proje grupları ortak rezervasyona bağlanır. Yerel uygulama varsayılanı günlük200 çağrı, aynı anda2 bulut çağrısı, sohbet için1 eşzamanlı ve20 günlük çağrı payıdır; bunlar resmî provider limitleri değildir, ayarlanabilir uygulama tavanlarıdır. Gerçek TPM/TPD politikası boş kalır; güvenilir paketlenmiş token üst sınırı sağlanmadan açılmaz. Bilinmeyen bakiyeler/kullanım null kalır. Yalnız provider'ın exact total-token bildirimi rezervasyonla uzlaştırılır; bilinmeyen/başlamış çağrı körlemesine iade edilmez. Custom parasal tavan isteğe bağlıdır; doluysa doğrulanmış maliyet üst sınırı olmayan çağrı gönderilmez. Yerel sayaç provider billing hard limit veya başka uygulamaların harcama sınırı değildir. Neuron=token dönüşümü yapılmaz.

Sağlık exact bağlantı/anahtar/model, kesin auth'ta bağlantı ve bilinen429 kapsamındaki proje bazındadır. Şema reddi, yerel deadline, iptal ve görüntü özellik uyuşmazlığı sağlıklı metin sağlayıcısını genel beklemeye sokmaz. Kaynak claim'i mevcut Core LeaseTable/OS claim sahibindedir; model_wait süresi bitse bile gerçek taşıyıcı kapanana kadar tutulur. Router yeni Scheduler/queue/Brain kurmaz. Çağıranın interactive/background sınıfı mevcut request bağlamında taşınır. Native model seçimi kadar owner bağlamı da plan/taşıma öncesinde doğrulanır ve ContextVar tokenıyla geri yüklenir.

`_LAST[owner]` kaldırıldı; SQLite owner/request/call/attempt izleri politika, ana/yedek, gerçek model, atlama, durum/finish, rezervasyon ve gerçek kullanımı ayrı gösterir. Prompt, cevap ve anahtar tutulmaz. Streaming uygulanmış gibi gösterilmez; ilk-token ölçülmediyse null'dır. Kısmi structured çıktı Core etkisi olamaz.

## Emeklilik ve dört kapanış koşulu

| Dikiş | Sözleşme | Eski göçü | Kullanıcı bağlantısı | Emeklilik |
|---|---|---|---|---|
| Model seçimi/repair | Typed ModelRequest → RoutePlan → exact adapter, en çok2 fiziksel deneme | Brain/sohbet/araştırma/worker/vision taşındı | Mevcut model_wait/Brain/Web akışları | `smart_router.run`, `task_type`, `_with_models`, `ollama_model_for`, `_ollama_task`, özel yerel retry yok |
| Gemini/görüntü | Owner-scoped veri izni + doğrulanmış özellik | Public-only/local-only varsayımları izin kapılarına taşındı | Kurulum tercihleri, gerçek image-parts, yerel yetenek kontrolü | Eski direct `_ask_image` yolu yok |
| Özel API | Owner secret/endpoint/revision/protokol/rol | Eski vendor metadata/secret disabled korunur | Gerçek Bridge CRUD/model listesi/açık tek test/form | `_PAID`, sabit vendor enum/kart/adapter ve eski ücretli seçici kaldırıldı |
| Kullanım/kota | Aynı ledger, shared scope, null unknown, kaynak payı | Sayaç ve request trace genişledi | Ayarlar/istek izleri/mevcut runtime beklemesi | `_LAST`, ayrı model dolaşımı/genel provider cezası otoritesi yok |

Kodun göçü ürünün canlı kabulünü kapatmaz. İncelenmiş model kartı, ücretsiz plan beyanı, gerçek hesap uygunluğu ve Brain rol yeterliliği ayrı kanıtlardır. Brain exact model/owner/bağlantı/source-fingerprint için mevcut tam20 örneklik holdout'ta ≥%95, sıfır kritik yanlış-action ve sıfır effect ister. Manuel `brain_output_diagnose_holdout.py --run` normal ücretsiz adayla; `--qualify-local` veya açık `--qualify-connection ID --accept-paid` yalnız seçilmiş bağlantıyla ölçer. Quick bağlantı testi rolü açmaz; script CI'da gerçek modele çalıştırılmaz. Kanıtın süresi7 gündür; kaynak/anahtar/bağlantı değişince geçersizleşir. Bu korpus bütün ürün veya tüm Windows yeteneklerinin canlı kabulü değildir.

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
