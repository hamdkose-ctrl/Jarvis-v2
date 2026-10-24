# Jarvis Bounded Delegation v1

## Durum ve amaç

Bu belge, Hermes veya gelecekteki herhangi bir dış/sub-agent kullanıldığında delegation sonucunun Jarvis Core'a hangi sınırlar içinde dönebileceğini tanımlayan mimari sözleşmedir. Bu değişiklik sub-agent runtime kurmaz, Hermes'i içe aktarmaz ve mevcut yürütme kodunu değiştirmez.

Kaynak-doğrulanmış temel omurga `Jarvis Core → DecisionContext / Permission / Effect Policy → Worker veya Adapter → WorkerResult + Evidence / Receipt → Core State Reducer / Completion Policy` biçimindedir. Core; owner, capability, retry/reconcile ve global completion kararlarının otoritesidir. Worker veya dış ajan yalnız kendi çağrısının sonucunu üretir.

## 1. Authority sınırı

Parent Jarvis Core task/goal sahibidir. Child agent, model, dış servis veya gelecekteki sub-agent **authority kaynağı değildir**.

Child yalnız şu sınıflardan birini döndürebilir:

- öneri / proposal;
- salt-okunur observation;
- `WorkerResult` biçimine dönüştürülebilecek result/evidence adayı.

Child çıktısındaki `done`, `approved`, `authorized`, `retry`, `permission granted` veya benzeri bir ifade Core kararı sayılmaz. Serbest metin, model cevabı veya child'ın kendi iç durumu Jarvis global state'ine doğrudan yazılamaz.

Child:

- permission yükseltemez veya grant üretemez;
- GoalState yazamaz;
- Reducer/CAS'i atlayamaz;
- kendi başına side effect başlatamaz;
- yeni capability/domain yetkisi açamaz;
- global `done`, `waiting` veya `failed` kararı veremez.

Yeni bir effect gerekiyorsa child bunu ancak proposal olarak Core'a döndürür. Effect'in gerçekten yürütülmesi mevcut karar sırasına geri girer: Domain invariant → Decision Authority → Permission → Effect Policy → Worker.

## 2. Delegation zarfı

Her bounded delegation çağrısı parent tarafından sınırlandırılmış bir zarfla tanımlanır. En az şu bağlar parent tarafında sabitlenir:

```yaml
delegation:
  owner: <job owner>
  job_id: <parent job>
  step_id: <parent step>
  command_id: <delegation command>
  attempt: <attempt>
  expected_job_version: <parent canonical version>
  allowed_capability:
    id: <capability id>
    version: <capability version>
  input_digest: <canonical input digest>
  budget: <bounded resource/work budget>
  deadline: <absolute deadline or equivalent bounded timeout>
```

Bu belge yeni runtime şeması uygulamaz; alanlar güvenlik sözleşmesini tarif eder. Mevcut WorkerResult v1 fence'i `owner`, `job_id`, `step_id`, `command_id`, `attempt`, `expected_job_version`, `capability_id`, `capability_version` ve `input_digest` alanlarının tamamını doğrular. Bounded delegation bu mevcut fence disiplinini zayıflatamaz.

`budget` ve `deadline`, parent'ın child'a verdiği üst sınırlardır. Child bunları artıramaz, sıfırlayamaz veya kendi cevabıyla genişletemez. Mevcut execution architecture kaynak bütçelerinin içerik/model tarafından artırılamayacağını ve timeout/cancellation sınırlarının capability politikasına ait olduğunu tanımlar. Gelecekteki delegation adapter'ı aynı ilkeyi korumalıdır.

## 3. Child sonucunun kabulü

Child sonucu Core'a döndüğünde parent en az aşağıdakileri doğrular:

1. `owner/job/step/command/attempt/expected_job_version` parent execution identity/fence ile aynıdır.
2. Sonuç yalnız parent'ın verdiği `allowed_capability` ve capability version kapsamındadır.
3. `input_digest` parent'ın child'a verdiği girdinin digest'iyle aynıdır.
4. Sonuç izin verilen budget içinde üretilmiştir; doğrulanamayan veya aşılmış budget başarı sayılmaz.
5. Sonuç deadline içinde dönmüştür; deadline sonrası sonuç stale/unknown kabul edilir ve state değiştiremez.
6. Evidence/result yapısı beklenen sözleşmeyle doğrulanabilir durumdadır.

Mevcut `worker_result.accept()` bütün immutable execution fence alanlarının birebir eşleşmesini ister ve uyuşmazlığı `FenceError` ile fail-closed reddeder. WorkerResult doğrulayıcısı worker çalıştırmaz ve GoalState mutate etmez. Dolayısıyla child sonucu doğrudan state yazısı değil, önce bu sınıra girecek bir adaydır.

Budget ve deadline bugün WorkerResult v1'in fence alanları değildir. Bu belge bunları gelecekteki bounded-delegation adapter'ının parent-side acceptance önkoşulu olarak sabitler; mevcut WorkerResult şemasını değiştirmez.

## 4. Canonical state sınırı

Child sonucu canonical state'i doğrudan değiştiremez.

Kabul yolu:

```text
child proposal / observation / result candidate
→ parent identity + capability + digest + budget + deadline validation
→ WorkerResult/evidence acceptance
→ Core State Reducer proposal
→ expected_version kontrolü
→ CAS
→ Completion Policy
```

Mevcut `worker_result_commit.commit()` yalnız zaten kabul edilmiş WorkerResult'ı evidence'a çevirir; canonical GoalState kimliğini ve `expected_job_version` değerini tekrar doğrular, evidence'ı Core State Reducer üzerinden ekler ve `compare_and_swap` ile persist eder. Stale sürüm evidence yazamaz.

Bu nedenle child'ın başarılı dönmesi, hatta geçerli WorkerResult üretmesi bile global completion değildir. Global state ve completion yalnız Core'un mevcut Reducer/CAS ve Completion Policy hattından çıkar.

## 5. Failure, timeout ve unknown

Child `failed`, timeout, malformed, stale veya `unknown` sonuç verdiğinde bounded delegation katmanı otomatik retry veya yeni effect başlatamaz.

Kurallar:

- failure yeni attempt yetkisi vermez;
- timeout aynı child/effect çağrısının kör tekrarına izin vermez;
- unknown sonuç başarıya çevrilmez;
- child kendi fallback worker'ını effect için otomatik başlatamaz;
- yeni attempt, reconciliation veya başka capability seçimi yalnız Core policy kararıdır.

Bu sınır mevcut crash-recovery ilkesini korur: intent var fakat receipt yoksa effect `unknown` olur, salt-okunur reconciliation gerekir ve kör retry yasaktır. Doğrulanmış receipt varsa dış effect tekrar edilmez. Delegation bu güvenliği aşan ikinci bir retry motoru oluşturamaz.

## 6. Paralel child sonuçları

Birden fazla child paralel çalıştırılabilse bile her sonuç bağımsız proposal/observation/WorkerResult adayıdır.

Paralel sonuçların:

- çoğunluk oyu,
- aynı cevabı vermesi,
- bir child'ın `done` demesi,
- bütün child'ların `succeeded` dönmesi

global completion üretmez.

Parent her sonucu kendi fence ve capability kapsamıyla doğrular. Kabul edilen evidence canonical hatta ayrı ayrı girebilir; Job/Goal'ın gerçekten tamamlanıp tamamlanmadığını Completion Policy üzerinden Core belirler. Child'lar birbirlerinin authority'sini veya budget'ını miras alamaz.

## 7. Fail-closed red koşulları

Aşağıdakilerden biri varsa child sonucu canonical state'e uygulanamaz:

- owner veya parent execution identity uyuşmuyor;
- expected job version stale;
- capability id/version parent'ın allowed capability sınırından farklı;
- input digest uyuşmuyor;
- budget aşılmış veya güvenilir biçimde doğrulanamıyor;
- deadline geçmiş;
- evidence/result şeması eksik veya belirsiz;
- child permission/grant yükseltmeye çalışıyor;
- child doğrudan GoalState/global completion iddiasını state değişikliği olarak sunuyor;
- sonuç yeni bir side effect'i parent Core kararı olmadan başlatmayı gerektiriyor.

Red edilen sonuç yeni effect veya retry tetiklemez. Core güvenli biçimde `blocked`, `failed`, `waiting`, reconcile veya yeni attempt kararını kendi politikasıyla verir.

## 8. Mevcut kaynaklarla uyum

Bu sözleşme mevcut mimarinin şu doğrulanmış sınırlarını genişletmeden kullanır:

- `modules/worker_result.py`: WorkerResult v1 saf/fail-closed boundary validator'dır; worker dispatch etmez, GoalState mutate etmez ve immutable fence'in tamamını eşleştirir.
- `modules/worker_result_commit.py`: kabul edilmiş sonucu canonical evidence olarak yalnız Reducer + CAS yoluyla yazar; identity ve expected version uyuşmazlığını reddeder.
- `JARVIS_EXECUTION_ARCHITECTURE_V1.md`: Core owner/capability/retry/completion otoritesidir; Worker yalnız kendi çağrısının sonucunu döndürür; global `done/waiting/failed` Core/Completion Policy kararıdır; model/worker/watcher yalnız proposal/result/event üretir.
- Aynı mimari crash recovery'de unknown effect için blind retry'ı yasaklar ve resource budget'ın içerik/model tarafından artırılamayacağını belirtir.

Bounded delegation bu omurganın dışına ikinci dispatcher, ikinci permission sistemi, ikinci state authority veya ikinci completion authority ekleyemez.

## 9. Kapsam dışı

Bu belge yalnız mimari delegation boundary sözleşmesidir. Aşağıdakiler kapsam dışıdır:

- gerçek sub-agent runtime veya process/IPC uygulaması;
- Hermes import, install veya entegrasyonu;
- scheduler veya queue;
- yeni planner;
- RuntimeEvent subscription;
- `goal_executor`, reducer veya permission kodu değişikliği;
- yeni retry/reconciliation motoru;
- CI, watcher, `AGENTS.md` veya test değişikliği.

Bu belge dış/sub-agent backend seçmez ve çalıştırmaz. Yalnız gelecekteki child sonuçlarının Jarvis Core authority, WorkerResult fencing, evidence ve Reducer/CAS sınırlarını aşmadan nasıl kabul edilebileceğini sabitler.
