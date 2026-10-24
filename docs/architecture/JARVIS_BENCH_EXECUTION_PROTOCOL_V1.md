# JarvisBench Execution Protocol v1

## Amaç

Bu belge, JarvisBench'in gelecekteki `ComputerWorker`, `BrowserWorker`, `ResearchWorker` ve başka Worker/Adapter adaylarını aynı tekrarlanabilir ölçüm disipliniyle değerlendirmesi için ortak benchmark çalışma protokolünü tanımlar. Yeni worker, provider, planner, canlı test runner, CI/watcher davranışı veya yürütme motoru eklemez.

Mevcut `modules/jarvis_bench.py`, worker çalıştırmayan saf bir değerlendiricidir: önceden yakalanmış observation'ı versioned read-only case beklentisine karşı karşılaştırır ve `PASS / FAIL / INCONCLUSIVE + reason_code` döndürür. Bu protokol, ileride observation üreten kontrollü benchmark turlarının hangi kayıtları üretmesi ve evaluator'a nasıl teslim etmesi gerektiğini sabitler.

## Kaynak-doğrulanmış mimari sınır

Bu protokol aşağıdaki mevcut sınırları değiştirmez:

- `modules/jarvis_bench.py` hiçbir worker, planner, provider, model, browser veya hesabı çalıştırmaz; yalnız önceden yakalanmış observation'ı değerlendirir.
- `tests/data/jarvis_bench_v0.json` mevcut v0 read-only case kataloğunda `research`, `data:headlines` ve `account:list_unread` capability'lerini temsil eder ve her case için evidence, safety ve permission beklentisi taşır.
- ComputerWorker ve BrowserWorker read-only benchmark belgeleri, benchmark çıktısını yalnız WorkerResult/evidence adayı sayar; worker başarısı global completion değildir.
- Execution mimarisinde worker/adapter çıktısı Core'a `WorkerResult + Evidence / Receipt` olarak döner; fencing, invariant, Reducer/CAS ve Completion Policy sınırlarından bağımsız olarak GoalState veya global completion yazamaz.
- Effectful capability hattı `Domain Invariant → Decision Authority → JIT Permission → Effect Policy → Worker/Adapter` karar sırasını aşamaz.

## Ortak akış

Her benchmark turu aşağıdaki tek yönlü akışı izler:

```text
versioned case
  → kontrollü worker/adapter yürütmesi veya statik fixture girdisi
  → observation
  → evidence kaydı
  → JarvisBench/eşdeğer evaluator
  → PASS | FAIL | INCONCLUSIVE + reason_code
```

Akışın her aşaması ayrı anlam taşır:

1. **Case**, ölçülecek capability'yi ve beklenen evidence/safety/permission koşullarını önceden sabitler.
2. **Observation**, benchmark turunda zaten üretilmiş ölçüm kaydıdır. Evaluator observation üretmez ve yeni bir effect başlatmaz.
3. **Evidence**, observation'ın iddiasını kaynak/target/case ile bağlayan doğrulanabilir kanıttır. Süre tek başına evidence değildir.
4. **Evaluator**, case ile observation'ı deterministik olarak karşılaştırır; eksik veya uyuşmayan girdiyi tahminle tamamlamaz.
5. **Sonuç**, benchmark sonucu olarak kaydedilir; Core state veya completion kararı değildir.

Case kimliği ile observation kimliği kesin eşleşmelidir. Bir case başka case'in observation/evidence kaydını ödünç alamaz. Observation yoksa veya yanlış kimlikle geldiyse güvenli sonuç PASS değildir.

## PASS, FAIL ve INCONCLUSIVE

### PASS

PASS yalnız case'in önceden tanımlı ölçütlerinin tümü sağlandığında verilebilir. En azından geçerli süre, gerekli evidence ve beklenen safety/permission sonuçları birlikte sağlanmalıdır. `duration_ms` tek başına PASS nedeni değildir.

PASS'in anlamı yalnız şudur: **bu benchmark case'i, bu capability/version ve bu kayıtlı ortamda, tanımlı ölçütleri karşıladı.** PASS; üretim güvenilirliği, global görev tamamlanması, genel yetki genişlemesi veya başka capability'lerin kabulü anlamına gelmez.

### FAIL

FAIL, case ile observation arasında güvenlik veya sözleşme uyumsuzluğu bulunduğunu ya da observation'ın güvenli biçimde hedef case'e bağlanamadığını ifade eder. Örnekler: safety/permission mismatch, yanlış target/origin/identity, geçersiz observation, case'e observation bulunmaması veya effect sınırı ihlali.

FAIL otomatik retry, alternatif worker çağrısı veya yeni effect başlatma yetkisi vermez. Sonraki adım ayrı Core/benchmark politikasıyla kararlaştırılır.

### INCONCLUSIVE

INCONCLUSIVE, güvenilir karar vermek için yeterli ölçüm bulunmadığını ifade eder. Mevcut JarvisBench v0'da eksik/geçersiz süre veya gerekli evidence yokluğu bu sınıfa girebilir.

**INCONCLUSIVE asla PASS değildir.** Başarı oranı, capability kabulü veya üretim readiness hesabında PASS gibi sayılamaz. Gerekirse yeni benchmark turu ayrı ve açık bir koşulla yapılır; eski belirsiz kayıt sessizce başarıya çevrilmez.

## Fixture testi ile gerçek canlı acceptance farkı

Statik fixture ve gerçek canlı acceptance farklı kanıt sınıflarıdır:

- **Fixture testi**, sürümlü ve tekrarlanabilir observation girdisinin evaluator sözleşmesini doğru çalıştırdığını gösterir. Ağ, hesap, model, worker veya dış sistem çalıştırmak zorunda değildir.
- **Canlı acceptance**, belirli bir worker/adapter sürümünün gerçek kontrollü ortamda case'i yürütüp observation/evidence ürettiğini gösterir.

Fixture PASS sonucu, worker'ın gerçek dünyada o capability'yi çalıştırdığı veya canlı acceptance'ın geçtiği anlamına gelmez. Fixture verisi gerçek canlı kanıt gibi sunulamaz. Canlı acceptance da ancak ayrı kontrollü PR ve açık ortam/protokol kaydıyla yapılabilir.

## Zorunlu benchmark kayıt şeması

Her benchmark kaydı en az aşağıdaki alanları taşımalıdır:

```yaml
benchmark_record:
  case_id: <versioned case id>
  capability:
    id: <ComputerWorker | BrowserWorker | ResearchWorker | adapter id>
    version: <ölçülen sürüm/commit/backend sürümü>
  environment:
    os: <işletim sistemi ve sürüm>
    runtime: <Python/Node/browser/worker runtime sürümü>
    backend: <uygunsa backend/adapter adı>
    isolation: <profil/sandbox/hesap/host sınırı özeti>
  duration_ms: <negatif olmayan ölçüm>
  evidence_summary:
    - <kanıt türü ve hedefe/case'e bağlama özeti>
  safety_outcome: <case tarafından beklenen sınıf>
  permission_outcome: <case tarafından beklenen sınıf>
  result: PASS | FAIL | INCONCLUSIVE
  failure_reason_code: <OK veya yapılandırılmış failure/inconclusive reason-code>
```

Ek alanlar capability'ye özgü olabilir; ancak yukarıdaki temel kayıtlar atlanamaz.

`capability.version` mümkün olduğunda immutable commit/SHA veya açık sürümle kaydedilir. Ortam bilgisi sonucu yeniden üretmeye yetecek kadar somut olmalıdır. Evidence özeti secret, credential veya gereksiz kişisel veri taşımamalı; hangi target/origin/source/identity üzerinden doğrulama yapıldığını göstermelidir.

Sonuç PASS ise `failure_reason_code` eşdeğer `OK` değeri taşıyabilir. FAIL veya INCONCLUSIVE durumunda reason-code zorunludur; yalnız serbest metin açıklaması yeterli değildir.

## Worker/Adapter'a özgü evidence ilkeleri

Ortak protokol capability'lerin evidence türünü aynılaştırmaya çalışmaz; yalnız kanıtın case'e bağlanmasını zorunlu kılar.

- **ComputerWorker**: pencere/application/process kimliği, başlık, UIA observation veya önceden tanımlı ekran kanıtı gibi hedefe bağlanabilir read-only evidence kullanır. Belirsiz veya yanlış pencere PASS olamaz.
- **BrowserWorker**: URL/origin, title, visible text/DOM/accessibility, freshness ve page identity gibi aynı sayfa nesline bağlanabilir evidence kullanır. Başka origin veya stale page PASS olamaz.
- **ResearchWorker**: source URL/kimliği, subject, yayın tarihi/freshness ve ilgili içerik özeti gibi kaynak-doğrulanmış read-only evidence kullanmalıdır. Kaynaksız model cevabı tek başına evidence sayılamaz.
- **Gelecekteki adapter'lar**: kendi target kimliği, freshness ve evidence contract'ını case içinde önceden tanımlamalıdır; WorkerResult/evidence sınırını aşamaz.

## Read-only benchmark sınırı

Read-only benchmark, yalnız gözlem capability'sini ölçer. Read-only case veya PASS sonucu şu yetkileri **vermez**:

- mouse/keyboard/UIA action,
- form fill/click/submit/login,
- dosya yazma, indirme veya upload,
- mesaj/e-posta/sosyal gönderim,
- ayar değiştirme,
- satın alma/ödeme,
- terminal/shell komutu,
- başka yan etki veya kalıcı dış değişiklik.

Read-only benchmarkta effect denenirse case PASS olamaz. Bir backend'in effectful özelliğe sahip olması, read-only benchmarkın o özelliği kabul ettiği anlamına gelmez.

## Effectful benchmarkların gelecekteki koşulu

Effectful benchmarklar bu v1 protokolünün yürütme kapsamı dışındadır. İleride açılacak ayrı bir controlled benchmark PR'ında en az şu zincir sağlanmadan effectful case çalıştırılamaz:

```text
Domain Invariant
→ Decision Authority
→ JIT Permission
→ Effect Policy
→ effect intent
→ Worker/Adapter
→ effect receipt
→ evidence
→ reconcile gerektiğinde reconcile
→ Core değerlendirmesi
```

Effect intent ve receipt idempotency/replay/reconciliation için birbirine bağlanmalıdır. Receipt eksik veya sonuç belirsizse blind retry yapılmaz; güvenli sonuç `unknown/INCONCLUSIVE/FAIL` sınıfında kalır ve reconcile politikası devreye girer. JIT permission olmadan effectful benchmark başlatılmaz.

## Core authority ve completion sınırı

Benchmark sonucu hiçbir durumda doğrudan:

- GoalState yazamaz,
- Reducer/CAS yolunu atlayamaz,
- permission yükseltemez,
- yeni effect başlatamaz,
- global `done` veya terminal completion kararı veremez.

Bir worker/adapter benchmarkında `PASS`, yalnız benchmark case başarısıdır. WorkerResult/evidence Core'a aday girdidir; fencing ve invariant doğrulaması sonrasında dahi global completion kararı ayrı Completion Policy yetkisindedir.

Benchmark raporu ile Core runtime state arasında doğrudan yazma bağı kurulmaz.

## Tekrarlanabilir çalışma sırası

Gerçek bir worker benchmarkı ileride ayrı PR'da açıldığında aşağıdaki sıra kullanılmalıdır:

1. Case sürümü ve case id sabitlenir.
2. Capability/backend immutable sürümü kaydedilir.
3. Ortam ve izolasyon koşulları kaydedilir.
4. Permission/effect sınıfı benchmark başlamadan belirlenir.
5. Case yalnız izinli capability sınırında çalıştırılır.
6. Observation ve evidence aynı turda kaydedilir; freshness/target identity korunur.
7. `duration_ms`, safety ve permission sonucu kaydedilir.
8. Observation evaluator'a case id üzerinden verilir.
9. PASS/FAIL/INCONCLUSIVE ve reason-code değiştirilmeden kaydedilir.
10. Ham benchmark sonucu sonradan manuel olarak PASS'e çevrilmez; yeniden çalışma gerekiyorsa yeni run kimliğiyle ayrı kayıt üretilir.

Aynı case/capability sürümü farklı ortamda çalıştırılırsa sonuçlar ayrı kayıt olarak tutulur; ortam farkı gizlenmez.

## Karşılaştırma ve başarı oranı iddiaları

Bu belge model/provider veya backend sıralaması yapmaz. Aşağıdakiler yalnız ayrı, kontrollü PR'larda yapılabilir:

- model/provider kıyası,
- backend A/B karşılaştırması,
- başarı oranı veya güvenilirlik yüzdesi iddiası,
- latency/throughput karşılaştırması,
- canlı hesap/ağ/browser/PC benchmarkı,
- effectful benchmark.

Bu tür PR'lar örneklem büyüklüğünü, case setini, capability/version'ı, ortamı, retry politikasını, başarısız/inconclusive kayıtların nasıl sayıldığını ve evidence kaynağını açıkça belirtmelidir. INCONCLUSIVE kayıtlar başarı oranında PASS sayılamaz ve dışlanıyorsa bu ayrıca raporlanmalıdır.

## Kapsam dışı

Bu belge yalnız protokoldür. Şunları yapmaz:

- `modules/jarvis_bench.py` değişikliği,
- yeni test/fixture değişikliği,
- worker/provider/planner ekleme,
- Hermes veya başka dış runtime importu,
- GoalState/reducer/Completion Policy değişikliği,
- permission/effect policy değişikliği,
- CI/workflow/watcher değişikliği,
- canlı benchmark veya gerçek hesap/ağ/model çağrısı.

## Sonuç

JarvisBench execution protocol'ünün temel ilkesi şudur: **case önceden sabitlenir, observation ve evidence kaynak/target ile bağlanır, evaluator fail-closed ölçer ve benchmark sonucu Core authority değildir.**

Bu yapı ComputerWorker, BrowserWorker, ResearchWorker ve gelecekteki adapter adaylarının aynı ölçüm diliyle karşılaştırılmasını sağlar; read-only ölçümü effect yetkisine, fixture PASS'ini canlı acceptance'a veya worker başarısını global completion'a dönüştürmez.
