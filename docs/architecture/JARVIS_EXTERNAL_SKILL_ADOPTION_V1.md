# Jarvis External Skill Adoption v1

**Durum:** Mimari kabul ve güvenlik sözleşmesi.

**Amaç:** Hermes veya başka ekosistemlerden gelen skill, plugin ve tool adaylarının Jarvis'e hangi kapılardan geçerek alınabileceğini tanımlar. Bu belge plugin runtime kurmaz, dış kod import etmez ve yeni bir execution engine veya tool catalog oluşturmaz.

## 1. Değişmez authority sınırı

Dış skill/plugin/tool yalnız bir **capability adayıdır**; authority kaynağı değildir.

Jarvis'in mevcut mimari sınırı değişmez:

```text
Jarvis Core
→ DecisionContext
→ Domain Invariant
→ Decision Authority
→ JIT Permission
→ Effect Policy
→ Worker / Adapter
→ WorkerResult + Evidence / Receipt
→ Core State Reducer / CAS
→ Completion Policy
```

Dış aday bu hattın yerine geçemez veya paralel ikinci bir Core/yürütücü kuramaz. `JARVIS_CAPABILITY_INTAKE_V1.md` dış kod, skill, plugin, MCP veya agent'ın ikinci Core, GoalState yazarı ya da izin otoritesi olamayacağını; `JARVIS_HERMES_ADAPTER_BOUNDARY_V1.md` ise dış runtime'ın yalnız adapter/worker adayı olabileceğini sabitler.

## 2. Kabul akışı

Bir dış adayın Jarvis'e kabul sırası şöyledir:

```text
candidate inventory
→ lisans / bağımlılık / risk incelemesi
→ read-only benchmark
→ adapter
→ manifest policy binding
→ WorkerResult / evidence acceptance
```

Bu aşamalar atlanamaz ve bir önceki aşamadaki başarı sonraki aşamanın otomatik kabulü değildir.

### 2.1 Candidate inventory

Aday önce yürütülmeden envantere alınır. En azından kaynak/provenance, sürüm veya sabitlenebilir kaynak kimliği, amaçlanan capability, beklenen girdiler/çıktılar ve öngörülen etki sınıfı kaydedilir. Envantere alınmak `AL` veya production kabulü değildir.

### 2.2 Lisans / bağımlılık / risk

Kaynak ve lisans, runtime/dependency uyumu ve adayın read-only, local write, external write veya physical etki sınırı değerlendirilir. Bilinmeyen veya doğrulanamayan önkoşul fail-closed biçimde kabulü durdurur ya da defer eder.

### 2.3 Read-only benchmark

İlk yürütülebilir değerlendirme mümkün olduğunda salt-okunur benchmark'tır. Amaç adayın doğru subject/target üzerinde güvenilir evidence üretebildiğini, yanlış veya stale girdiyi reddettiğini ve mevcut Jarvis baseline'ına karşı ölçülebilir olduğunu göstermektir.

**Read-only başarı, effectful capability kabulü anlamına gelmez.** Salt-okunur benchmark yalnız gözlem/evidence üretme yeterliliğini kanıtlayabilir; yazma, gönderme, tıklama, ödeme, paylaşma, fiziksel veya başka yan etkili davranış için authority vermez.

### 2.4 Adapter

Kabul edilen aday doğrudan Core'a veya mevcut kataloglara kontrolsüz biçimde import edilmez. Jarvis sözleşmesini uygulayan dar bir Worker/Adapter sınırının arkasında tutulur. Adapter dış adayın kendi authority, completion veya state iddialarını Jarvis authority'sine dönüştürmez; yalnız normalize edilmiş sonuç/evidence adayı üretir.

### 2.5 Manifest policy binding

Adapter capability olarak kullanılmadan önce mevcut Jarvis politika metadata'sına bağlanır: capability kimliği/sürümü, permission class, effect policy, decision authority, replay/reconciliation ve evidence contract açıkça belirlenir.

`modules/capability_manifest.py` manifesti read-only compatibility view olarak tanımlar; dispatcher veya ikinci tool catalog değildir. Manifest `_FIELDS` kümesi yalnız JSON uyumlu statik politika metadata'sı taşır. `from_tool_contract()` özellikle callable binding'leri dışarı açmadan adaptasyon yapar.

Bu nedenle **callable, Python fonksiyonu, process handle, runtime binding veya başka çalıştırılabilir binding manifest JSON'una girmez.** Çalıştırılabilir binding ayrı runtime/adapter katmanının sorumluluğudur.

### 2.6 WorkerResult / evidence acceptance

Dış adayın başarılı çalıştığını söylemesi canonical başarı değildir. Çıktı ancak Jarvis'in WorkerResult/evidence kabul hattından geçebilecek bir adaydır.

`worker_result.v1` immutable execution fence ister: `owner`, `job_id`, `step_id`, `command_id`, `attempt`, `expected_job_version`, `capability_id`, `capability_version` ve `input_digest`. Eşleşmeyen/stale/foreign sonuç canonical state'i değiştiremez.

Kabul edilmiş evidence dahi canonical GoalState'e yalnız Core State Reducer ve CAS hattından eklenebilir. Worker veya dış skill global completion kararı veremez; Completion Policy/Core karar verir.

## 3. Dış adayın yasak authority'leri

Hiçbir dış skill/plugin/tool:

- GoalState'e doğrudan yazamaz;
- Core State Reducer/CAS hattını bypass edemez;
- permission/grant üretemez veya mevcut permission kararını yükseltemez;
- kendi kendine effect başlatma authority'si edinemez;
- kendi runtime'ındaki `success`, `done` veya benzeri durumu Jarvis global `done` olarak ilan edemez;
- manifest metadata'sını kullanarak yeni bir dispatcher/execution engine kuramaz.

Bu yasaklar adayın kaynağından bağımsızdır; Hermes, başka bir açık kaynak proje, yerel plugin veya gelecekteki ekosistem aynı sınırdan geçer.

## 4. Effectful adaylar için zorunlu güvenlik hattı

Bir aday read-only sınırını aşıyorsa production yürütme için aşağıdaki sıra zorunludur:

```text
Domain Invariant
→ Decision Authority
→ JIT Permission
→ Effect Policy
→ Worker / Adapter
```

Read-only benchmark, bu zincirin hiçbir adımını önceden geçmiş sayılmaz.

- **Domain Invariant:** İstenen etki domain'in değişmez güvenlik kurallarına uymalıdır.
- **Decision Authority:** Capability'nin bu owner/job/step/target kapsamında yürütme yetkisi Core tarafından belirlenir.
- **JIT Permission:** Yan etkiden hemen önce güncel owner, target, grant ve politika yeniden değerlendirilir. Dış içerik veya skill permission yükseltemez.
- **Effect Policy:** Replay, write-ahead intent/receipt ve reconciliation gereksinimleri etki sınıfına göre uygulanır. Belirsiz etki kör retry ile yeniden başlatılmaz.

Adayın kendi güvenlik/izin sistemi varsa bu yalnız ek bir kısıt olabilir; Jarvis hattını gevşetemez veya onun yerine geçemez.

## 5. Kabul kararı ve reason-code kaydı

Her değerlendirme sonucu açık bir karara bağlanır:

```yaml
candidate_decision:
  candidate_id: <stable-id>
  decision: ACCEPT | REJECT | DEFER
  reason_code: <stable-reason-code>
  evidence_refs: []
```

Reason-code kısa, deterministik ve denetlenebilir olmalıdır. Örnek sınıflar:

- `SOURCE_OR_LICENSE_UNVERIFIED`
- `DEPENDENCY_INCOMPATIBLE`
- `RISK_BOUNDARY_UNKNOWN`
- `READONLY_BENCHMARK_FAILED`
- `ADAPTER_BOUNDARY_MISSING`
- `MANIFEST_POLICY_UNBOUND`
- `WORKER_RESULT_CONTRACT_MISSING`
- `EFFECT_POLICY_NOT_READY`
- `ACCEPTED_READONLY_ONLY`

Bu kayıt kararın sonucu ve doğrulanabilir provenance/evidence referanslarını taşır. **Chain-of-thought, gizli model muhakemesi veya serbest iç düşünce kaydedilmez.** Gerekçe reason-code ve gerektiğinde kısa, denetlenebilir açıklamayla sınırlıdır.

`DEFER`, başarısızlığı gizleyen bir başarı değildir: eksik önkoşul açıkça belirtilir ve aday authority kazanmaz. `REJECT` adayın mevcut biçimiyle kabul edilmediğini belirtir. `ACCEPT` yalnız belgelenmiş kapsam için geçerlidir; örneğin `ACCEPTED_READONLY_ONLY`, effectful kullanım izni vermez.

## 6. Fail-closed kuralları

Aşağıdakilerden biri doğrulanamıyorsa aday production capability sayılmaz:

- kaynak/provenance veya lisans/bağımlılık sınırı;
- risk/effect sınıfı;
- read-only benchmark sonucu;
- adapter sınırı;
- manifest policy binding;
- gerekli WorkerResult/evidence sözleşmesi;
- effectful adaylarda Domain Invariant → Decision Authority → JIT Permission → Effect Policy zinciri.

Eksik bilgi varsayımla doldurulmaz. Aday `DEFER` veya `REJECT` olarak kalır.

## 7. Mevcut kaynaklarla doğrulanan dayanaklar

Bu sözleşme mevcut depodaki şu sınırları değiştirmeden bir araya getirir:

- `docs/architecture/JARVIS_CAPABILITY_INTAKE_V1.md`: dış capability için kaynak/lisans/dependency, effect sınırı, Worker/Adapter, Permission/Effect/Evidence/Completion ve acceptance/benchmark kapıları; `AL` kontrolsüz import değildir.
- `docs/architecture/JARVIS_HERMES_ADAPTER_BOUNDARY_V1.md`: dış agent/skill Core authority değildir; GoalState/Permission/Effect/global completion sınırlarını geçemez.
- `docs/architecture/JARVIS_EXECUTION_ARCHITECTURE_V1.md`: tek Core, sabit karar sırası, WorkerResult fencing, Reducer/CAS ve Completion Policy sınırı.
- `modules/capability_manifest.py`: manifest read-only statik metadata görünümüdür; dispatcher değildir ve callable binding açmaz.
- `modules/worker_result.py`: immutable fence doğrulaması ve fail-closed result acceptance.
- `modules/worker_result_commit.py`: kabul edilmiş WorkerResult evidence'ının Reducer + CAS üzerinden canonical state'e eklenmesi.

## 8. Kapsam dışı

Bu belge aşağıdakileri yapmaz:

- plugin runtime veya install mekanizması kurmaz;
- yeni tool catalog veya execution engine oluşturmaz;
- Hermes import/install etmez;
- GoalState, reducer veya permission kodunu değiştirmez;
- CI veya watcher değiştirmez;
- `AGENTS.md` değiştirmez;
- test eklemez/değiştirmez.

Bu belge yalnız **external skill/plugin/tool adoption boundary** sözleşmesidir; runtime implementasyonu değildir.
