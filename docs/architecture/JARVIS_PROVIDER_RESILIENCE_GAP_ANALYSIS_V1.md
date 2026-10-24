# Jarvis Provider Resilience Gap Analysis v1

## Amaç ve kapsam

Bu belge, Jarvis-v2'nin provider/model hata dayanıklılığında **mevcut davranışı** kaynak koddan çıkarır ve kalan boşlukları tanımlar. Yeni provider, fallback runtime, Ollama kurulumu, worker, test, workflow veya dependency eklemez. Başarı/acceptance iddiası içermez.

İncelenen ana kaynaklar:

- `modules/goal_executor.py`
- `modules/failure_policy.py`
- `modules/llm.py`
- `modules/smart_router.py`
- `modules/completion_policy.py`
- `modules/worker_result.py`
- mevcut modelsiz/deterministik yollar (`modules/news_policy.py`, `modules/finance.py` ve bunlara bağlı mevcut akışlar)
- ilgili mevcut testler: `tests/test_goal_failure_policy.py`, `tests/test_quota_routing.py`, `tests/test_smart_router.py`, `tests/test_ollama_optional.py`, `tests/test_news_error_text.py`

## 1. Mevcut hata davranışı

`modules/failure_policy.py` ortak sınıflandırmayı şu kategorilere ayırır: `rate_limit`, `auth`, `dns`, `timeout`, `network`, `provider_down`, `environment` ve diğer genel sınıflar. HTTP 429 veya quota/rate-limit metni `rate_limit`; HTTP 401/403 veya API-key/unauthenticated benzeri metin `auth`; DNS çözümleme belirtileri `dns`; timeout türleri `timeout`; bağlantı reddi/kesilmesi `network`; 500/502/503/504 veya overloaded/service unavailable `provider_down`; eksik runtime/paket/dosya benzeri durumlar `environment` olur.

`failure_policy.recovery_action()` bugün yalnız strateji adı üretir; kendisi retry veya provider çağrısı yapmaz:

| Hata | Mevcut kategori | Mevcut recovery yönü | Kullanıcı aksiyonu? | Fail-closed noktası |
|---|---|---|---|---|
| 429 / quota / rate limit | `rate_limit` | `alternate_provider` | Genellikle hayır; tüm alternatifler bitmişse bekleme/ayar gerekir | Aynı başarısız provider başarı sayılmaz |
| Auth / 401 / 403 | `auth` | model/planner bağlamında `alternate_provider`, diğer bağlamda `request_connection` | Evet, çalışan alternatif yoksa bağlantı/anahtar gerekir | Başarısız auth sonucu tamamlandı sayılmaz |
| DNS yok | `dns` | `alternate_path` | Ağın düzelmesi gerekebilir | Ham başarısızlık yerine güvenli açıklama hedeflenir |
| Genel ağ kesintisi | `network` | `alternate_path` | Ağ veya alternatif yol gerekir | Başarısız çağrı başarı sayılmaz |
| Timeout | `timeout` | `alternate_path` | Genellikle hayır; alternatif yoksa bekleme gerekir | Timeout completion değildir |
| Provider 5xx/down | `provider_down` | `alternate_provider` | Genellikle hayır | Provider yanıt vermeden başarı yok |
| Ollama/runtime yok | çoğunlukla `environment` veya `LocalModelError` mesajı | `alternate_environment` / router'da sıradaki provider | Yerel-mod tek seçenekse kullanıcı aksiyonu gerekir | Ollama yokken yerel model sonucu uydurulmaz |
| Hiç uygun provider yok | router sonunda aggregate `RuntimeError` | otomatik provider kalmaz | Anahtar/onay/bekleme veya ortam düzeltmesi gerekebilir | Çağrı başarısız olur; ücretli modele otomatik geçilmez |

### 429

`modules/llm.py` provider adapter'ları provider içi sınırlı retry/model geçişi uygulayabilir; mevcut testler Groq tarafında 429'un aynı isteği sınırsız kör tekrar etmediğini ve cooldown/rate-limit bilgisinin tutulduğunu doğrular. `modules/smart_router.py` başarısız provider'ı cooldown'a alır ve sıradaki uygun ücretsiz provider'a geçer. Router otomatik havuzunda ücretli provider yoktur.

Gap: 429 bilgisi `failure_policy` içinde sınıflandırılsa da bu kategori Goal/Worker sonucuna zorunlu, makine-okunur bir `reason_code` olarak taşınmıyor. Son kullanıcı metni ile router attempt metadata'sı ayrı kanallarda kalıyor.

### Auth

Eksik kullanıcı anahtarı `smart_router.selection()` aşamasında provider'ın hiç çağrılmamasına yol açar; `skipped` kaydına “API anahtarı eksik” nedeni yazılır. Gerçek provider çağrısı 401/403 ile dönerse `failure_policy` bunu `auth` sınıfına sokar. Model/planner bağlamında alternatif provider denenebilir; entegrasyon/hesap bağlamında politika `request_connection` yönü verir.

Gap: missing-key (`skipped`) ile gerçek 401/403 (`auth failure`) aynı üst düzey Goal failure sözleşmesinde tek tip reason-code şemasına normalize edilmiyor.

### Ağ yokluğu / DNS

`failure_policy.explain()` DNS/network için güvenli açıklama üretir. `ollama_hint.offline_text()` gerçek internet yokluğu tespit edilebiliyorsa daha doğrudan “internet bağlantın yok” metni döndürebilir. `goal_executor` provider kategorilerinde raw `str(exc)` yerine bu güvenli açıklamayı kullanır.

Gap: `alternate_path` bir strateji adıdır; Goal executor seviyesinde deterministik bir “şu modelsiz adımı çalıştır” yürütme sözleşmesi değildir. Modelsiz yol varsa ilgili domain kodunun ayrıca buna sahip olması gerekir.

### Timeout

Provider adapter'ları timeout kullanır; `failure_policy` timeout'u ayrı kategoriye çevirir. Smart Router başarısız provider'ı cooldown'a alıp sıradaki provider'a geçebilir.

Gap: provider içi retry ile router provider-fallback kararları tek merkezi retry budget/reason kaydında birleşmiyor. Kullanıcıya “kaç deneme yapıldı / hangi katman denedi” bilgisi standart Worker evidence biçiminde taşınmıyor.

### Provider yok / uygun provider kalmaması

`smart_router.selection()` provider'ları gizlilik modu, ücretsiz hesap onayı, API key ve cooldown nedeniyle eleyebilir. Tüm adaylar bittikten sonra `smart_router.run()` kontrollü provider/error/status özetlerinden bir `RuntimeError` üretir ve açıkça “Ücretli modele geçilmedi” der.

Gap: bu son aggregate `RuntimeError`, `failure_policy.classify()` tarafından zorunlu olarak `rate_limit/auth/environment` gibi özgül kategoriye dönmeyebilir. Dolayısıyla `goal_executor` bu durumda `_PROVIDER_CATEGORIES` dışına düşüp `str(exc)` yolunu kullanabilir. Metin router tarafından kontrollü üretilmiş olsa da **makine-okunur reason-code zinciri kopar**.

### Ollama yok

`modules/llm.py` Ollama bağlantı hatasını `LocalModelError(ollama_hint.need(...))` olarak yükseltir; model 404 ise kullanıcıya `ollama pull <model>` yönlendirmesi içeren `LocalModelError` üretir. `smart_router.run()` Ollama `LocalModelError` için “ollama_missing” hint'i kaydedebilir ve diğer provider adaylarına devam eder. Yerel gizlilik modunda seçim yalnız Ollama olduğundan alternatif bulut provider yoktur.

Gap: `failure_policy.explain()` `LocalModelError` ve `CloudError` için mesaj varsa **kategori-temelli normalize metinden önce doğrudan exception mesajını döndürür**. Bugünkü Ollama/CloudError üreticileri çoğunlukla kontrollü mesaj üretse de bu, “raw provider mesajı asla sızmaz” garantisini merkezi sözleşme seviyesinde sağlamaz.

## 2. Ham hata / reason-code ayrımı

### Güvenli metne çevrilenler

`goal_executor.py` içindeki `_PROVIDER_CATEGORIES` şu sınıfları kapsar: `RATE_LIMIT`, `AUTH`, `DNS`, `NETWORK`, `TIMEOUT`, `PROVIDER_DOWN`, `ENVIRONMENT`. Tool adımı bu sınıflardan biriyle düşerse `failure_policy.explain(exc)` kullanılır ve sonuç metni `privacy.redact(..., force=True)` üzerinden geçirilir. Mevcut `tests/test_goal_failure_policy.py` bu yolun provider secret'ını kullanıcı metnine taşımadığını doğrular.

### Ham/özgül metin yolunda kalanlar

Provider kategorisi dışında kalan exception'lar `goal_executor` içinde `str(exc)` yoluna gider; yine privacy-redact uygulanır. Bu davranış dosya bulunamadı/ValueError gibi araç-spesifik açıklamaları korumak için bilinçlidir.

İki önemli gap vardır:

1. `failure_policy.explain()` `LocalModelError` ve `CloudError` mesajını doğrudan döndürebilir. Bu exception sınıflarının tüm üreticilerinin sonsuza kadar güvenli/sanitize metin üretmesine güveniliyor.
2. Goal failure çıktısı bugün tipik olarak `{'state':'failed','text':...}` biçimindedir; `failure_policy.classify()` sonucu **zorunlu `reason_code` alanına yazılmaz**. Kategori mevcut ama kullanıcı/Goal/Worker katmanları arasında yapısal olarak taşınmaz.

Sonuç: “ham metni kullanıcıya hiç verme” davranışı kısmen var; “her provider hatası reason-code'a dönüşür” davranışı henüz yoktur.

## 3. Retry / kullanıcı aksiyonu / fallback / fail-closed matrisi

| Sınıf | Retry yapılabilir mi? | Kullanıcı aksiyonu gerekir mi? | Fallback mümkün mü? | Mevcut güvenli sonuç |
|---|---|---|---|---|
| `rate_limit` | Evet, fakat aynı çağrıyı kör tekrar değil; provider/model/router politikasıyla sınırlı | Alternatifler bittiyse bekleme gerekebilir | Evet, uygun ücretsiz provider varsa | Başarısız provider cooldown; completion yok |
| `auth` | Aynı bozuk credential ile kör retry hayır | Çalışan alternatif yoksa evet | Model/planner'da evet | Provider skip/fail; bağlantı gerekebilir |
| `dns/network` | Ağ düzelmeden kör retry hayır | Bazen | Alternatif path veya modelsiz domain yolu varsa | Fail/alternatif yol |
| `timeout` | Sınırlı retry mümkün | Genellikle hayır | Alternatif provider/path varsa | Fail/alternatif yol |
| `provider_down` | Sınırlı retry/fallback mümkün | Genellikle hayır | Evet | Fail/alternatif provider |
| Ollama yok/model yok | Aynı eksik runtime/model ile kör retry hayır | Yerel-only modda evet | Auto modda bulut provider uygunsa evet | LocalModelError + alternatif deneme |
| Uygun provider yok | Hayır | Evet veya cooldown sonunu beklemek gerekir | O anda yok | Aggregate failure; ücretliye otomatik geçiş yok |

Bu tablo “retry yapılabilir”i otomatik sonsuz retry olarak yorumlamaz. `goal_executor.SYSTEM` zaten “aynı başarısız isteği körlemesine yineleme” talimatını taşır; ayrıca effectful işlerde normal effect/receipt/reconcile kuralları ayrı kalır.

## 4. LLM yokken deterministik işlerin durumu

LLM yokluğu Jarvis'in bütün yeteneklerinin çalışamaz olduğu anlamına gelmiyor.

Kaynakta açık modelsiz yollar var:

- `modules/finance.py`: döviz/kripto/altın/BIST okuma ve hesaplama yüzeyi modelsiz tasarlanmıştır.
- `modules/news_policy.py`: haber tamamlanma politikası ve modelsiz kayıtlı kurtarma davranışları içerir; kaynak/evidence mevcutsa model yokluğu tek başına doğrulanmış kaynağı yok etmez.
- `goal_executor.SYSTEM`: haber kaynak seçimi/veri toplama için yeni model/API anahtarı gerekmediğini açıkça belirtir; `data:headlines`, `research`, `verify` gibi deterministik/araç tabanlı adımlar model dışında gerçek evidence üretebilir.
- Dosya/tablo/PC gibi bazı domain operasyonlarının kendileri de model çağrısından bağımsız olabilir; ancak Goal planlama katmanı model gerektiriyorsa bu operasyonların var olması otomatik olarak hedef yürütücüsünün modelsiz devam edeceği anlamına gelmez.

Ana gap: “bu adım deterministik ve model gerektirmiyor” bilgisi Goal executor/provider failure anında ortak bir capability metadata'sı olarak kullanılmıyor. Yani model çöktüğünde Core'un genel bir deterministik-step devam politikası yok; modelsiz kurtarma bugün domain-spesifik yollarla sağlanıyor.

## 5. Doğrulanmış partial WorkerResult sınırı

`modules/worker_result.py` mevcut şemada yalnız `status in {'succeeded','failed'}` kabul eder. Ayrı bir `partial` WorkerResult status'u **yoktur**. WorkerResult evidence listesi taşıyabilir ve fence (`owner`, `job_id`, `step_id`, `command_id`, `attempt`, `expected_job_version`, `capability_id`, `capability_version`, `input_digest`) tam eşleşmeden kabul edilmez.

Bu nedenle bugünkü kaynaklara göre:

### Verilebilecek / korunabilecek partial kanıt

- Provider/model düşmeden **önce** gerçek bir tool/read-only adapter tarafından doğrulanmış evidence üretilmişse bu evidence sonraki karar için korunabilir.
- Haber/research gibi domainlerde doğrulanmış kaynak makbuzu/evidence varsa Completion Policy bu kanıtı ayrı değerlendirir; model hatası var diye kanıt otomatik silinmez.
- Bir step başarısız olurken eldeki doğrulanmış evidence, ancak mevcut WorkerResult şemasının `failed` sonucu/evidence sözleşmesi ve doğru fence içinde taşınabiliyorsa kanıt olarak saklanabilir; bu global `done` değildir.

### Verilemeyecek durumlar

- Provider/model yalnız taslak metin üretmiş ama kaynak/receipt/evidence doğrulanmamışsa “partial success” denemez.
- 429/auth/network/timeout tek başına partial evidence değildir.
- Modelin “işin yarısı tamam” demesi WorkerResult evidence değildir.
- Yanlış/stale fence'li sonuç kabul edilemez.
- Completion Policy kanıtı kabul etmediyse worker/model sonucu global completion'a çevrilemez.
- Mevcut şemada resmi `status:'partial'` olmadığı için böyle bir status uydurulamaz.

Gap: “doğrulanmış partial teslim” ürün semantiği ile `worker_result.v1`'in yalnız succeeded/failed şeması arasında açık bir temsil boşluğu vardır. Sonraki kod PR'ı bu boşluğu çözmeden kullanıcıya partial WorkerResult adıyla yeni bir state sunmamalıdır.

## 6. Completion Policy ve fail-closed davranış

`modules/completion_policy.py` provider çağrısı yapmaz. `evaluate_evidence()` evidence check normal dönerse `COMPLETE`, `ValueError` ile yetersiz/geçersiz kanıt görürse `CONTINUE` verir; diğer exception'ları yutmaz. `job_decision()` yalnız mevcut job state'e bakar. Dolayısıyla provider hatası kendi başına completion kararı değildir.

Bu iyi bir sınırdır: provider/model “cevap verdi” diye GoalState done olmaz; evidence/Completion Policy ayrı kalır.

Gap: provider failure kategorileri Completion Policy'ye yapısal reason-code olarak aktarılmadığı için “waiting for quota”, “user action required”, “retryable provider outage”, “deterministic fallback available” ayrımı job state seviyesinde tek tip sözleşmeyle temsil edilmiyor.

## 7. Kaynak-kanıtlı gap özeti

1. **Sınıflandırma var, uçtan uca reason-code yok.** `failure_policy.classify()` güçlü bir ortak kategori üretir fakat Goal output/WorkerResult'a zorunlu alan olarak bağlanmamıştır.
2. **LocalModelError/CloudError message bypass'ı var.** `failure_policy.explain()` bu iki sınıfta doğrudan exception mesajını döndürür; merkezi sanitize garantisi eksiktir.
3. **Router fallback var, domain-level deterministic fallback genel değil.** Smart Router provider değiştirir; model gerekmeyen adımlara otomatik Core devamı yalnız domain-spesifik yerlerde vardır.
4. **Retry katmanları parçalıdır.** Provider adapter içi retry/model geçişi, router cooldown/fallback ve Goal planner'ın “başka yöntem dene” davranışı tek budget/reason ledger'ında birleşmez.
5. **“No provider” aggregate RuntimeError yapısal kategori kaybedebilir.** Kontrollü metin üretilse bile `failure_policy` category/reason-code zinciri standart değildir.
6. **Resmî partial WorkerResult yok.** Şema yalnız `succeeded/failed`; doğrulanmış kısmi evidence saklanabilir ama `partial` status'u kaynakta yoktur.
7. **User-action vs waiting vs retryable state ayrımı job seviyesinde zayıf.** Recovery action isimleri var, fakat bunlar Goal state/Completion kararına doğrudan bağlanmış yapılandırılmış alanlar değildir.

## 8. Sonraki kod PR'ı için en küçük önerilen kapsam

Bu belge kod değiştirmez. En küçük takip PR'ı, yeni provider veya runtime eklemeden yalnız mevcut davranışı yapısallaştırmalıdır.

### En küçük dosya listesi

1. `modules/failure_policy.py`
   - mevcut kategoriye stabil provider failure reason-code üretimi eklemek;
   - `LocalModelError`/`CloudError` için doğrudan mesaj bypass'ını güvenli normalize sözleşmeye almak veya yalnız açıkça güvenli kodlu mesajlara izin vermek.
2. `modules/goal_executor.py`
   - tool/provider failure çıktısına `reason_code`, `retry_class`/`user_action_required` gibi mevcut failure policy'den türetilen yapısal metadata eklemek;
   - ham/aggregate provider metnini completion semantiği yapmamak.
3. `modules/smart_router.py`
   - “hiç provider yok / tümü başarısız” sonucunu generic `RuntimeError` yerine failure policy'nin tanıyacağı stabil, sanitize bir failure sözleşmesine taşımak; mevcut ücretsiz-only politika korunmalı.

İlk PR'da `worker_result.v1` şemasını değiştirmek zorunlu değildir; partial-status konusu ayrı tasarım/test PR'ı olarak kalabilir. Böylece kapsam küçük tutulur.

### En küçük test listesi

Mevcut testleri genişletmek yeterlidir:

- `tests/test_goal_failure_policy.py`
  - 429/auth/DNS/network/timeout/provider_down/environment için yapısal `reason_code`;
  - secret/raw provider body sızmaması;
  - generic olmayan kullanıcı açıklaması.
- `tests/test_smart_router.py`
  - tüm provider'lar exhausted olduğunda stabil kategori/reason-code;
  - missing-key ile 401/403 ayrımı;
  - Ollama yok + bulut alternatif var/yok dalları.
- `tests/test_quota_routing.py`
  - 429 bounded retry/cooldown korunumu;
  - fallback sonrası başarı ve tüm fallback'ler bitince fail-closed.
- `tests/test_ollama_optional.py`
  - Ollama kurulu değil mesajının sanitize ve user-action-required olarak sınıflanması;
  - yerel-only modda bulut fallback yapılmaması.

İsteğe bağlı ama aynı PR'da ancak gerekirse: `tests/test_news_error_text.py` ile modelsiz doğrulanmış evidence'ın provider hatası yüzünden yanlışlıkla kaybolmadığını regression olarak kilitlemek.

## 9. Kapsam dışı

Bu analiz şunları önermiyor veya uygulamıyor:

- yeni provider eklemek;
- Ollama kurmak/başlatmak;
- ücretli modele otomatik geçmek;
- yeni fallback runtime yazmak;
- WorkerResult şemasına hemen `partial` eklemek;
- GoalState/Reducer/Completion Policy otoritesini provider katmanına taşımak;
- CI/watcher/workflow/dependency değiştirmek.

Ana hedef, sonraki küçük kod PR'ında **mevcut failure sınıflandırmasını uçtan uca yapısal ve fail-closed hale getirmek**, mevcut provider/router davranışını genişletmeden daha gözlenebilir kılmaktır.
