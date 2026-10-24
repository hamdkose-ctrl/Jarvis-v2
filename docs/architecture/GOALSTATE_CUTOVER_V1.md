# Canonical GoalState cutover v1 — migration/preflight sözleşmesi

Durum: **preflight sözleşmesi**. Bu doküman runtime cutover değildir; `goal_executor`, reducer/CAS, worker/effect/permission veya subscription davranışını değiştirmez.

## Kilitli otorite sınırı

- Hedef mimaride **GoalState global lifecycle authority** olur.
- Yürütme ayrıntıları global lifecycle state değildir. İleride ayrı bir **ExecutionRecord** step/output/waiting/retry gibi yürütme bağlamını taşır. Bu PR ExecutionRecord şeması veya runtime'ı eklemez.
- **Big-bang migration yoktur.** İlk gerçek cutover açık, geri alınabilir ve dar bir sınırdan yapılır.
- Mevcut runtime boyunca legacy `goal_executor` JSON journal **write authority** olarak kalır. Canonical GoalState bugün compatibility projection/sync katmanıdır; bu preflight dokümanı authority'yi tersine çevirmez.

## Kaynak kodda bugün doğrulanan sınır

`modules/goal_state.py`, `goal_state.v1` kimliğini `owner + job_id + goal + execution_mode` alanlarıyla kurar. `owner`, `job_id`, `goal` ve `execution_mode` immutable identity'dir; lifecycle state kümesi `pending/running/waiting/paused/failed/done/cancelled`, terminal kümesi ise yalnız `done/cancelled`dır.

`modules/goal_state_compat.py` legacy job'u canonical snapshot'a projekte eder. Mevcut eşleme:

| Legacy state | Canonical GoalState |
|---|---|
| `running` | `running` |
| `approval`, `question` | `waiting` |
| `review`, `paused`, `interrupted`, `blocked` | `paused` |
| `failed` | `failed` |
| `done` | `done` |
| `cancelled` | `cancelled` |

Bilinmeyen legacy state fail-closed `ValueError` üretir. Projection `owner=job['owner']`, `job_id=job['id']`, `goal=job['request']`, `execution_mode='agent'` kullanır. Canonical state terminal ise compatibility advance onu yeniden açmaz.

`modules/goal_state_save_hook.py`, yalnız biçimi ve owner namespace'i doğrulanan legacy goal-job kayıtlarını yakalar. Önce canonical GoalState'i sync eder, sonra legacy atomic write yapar. Canonical sync başarısız olursa tanı noktası kaydedilir, aynı exception yukarı yayılır ve legacy write/compensation çalıştırılmaz. Legacy write başarısız olursa canonical yazıyı önceki byte'lara compensate etmeye çalışır; compensation da başarısızsa fail-closed hata verir. Bu mekanizma migration compatibility katmanıdır; canonical authority cutover değildir.

### Persisted canonical snapshot bozulması

`modules/goal_state_store.py` için canonical dosya byte'larının UTF-8 olarak çözülememesi, JSON'un yarım/geçersiz olması veya JSON çözüldükten sonra `goal_state.validate()` sözleşmesini geçememesi tek bir persisted-state corruption sınırıdır. Bu durum normal CAS conflict veya kullanıcı girdisi hatası değildir.

Bozuk canonical snapshot fail-closed kabul edilir:

- `load()` bozuk snapshot'ı state olarak döndürmez.
- `compare_and_swap()` bozuk mevcut snapshot üzerine yazmaz.
- `compensate()` bozuk mevcut snapshot varken restore/delete yapmaz; `previous_bytes` bozuksa da mevcut state'e dokunmaz.
- Bozuk dosya otomatik silinmez, sıfırlanmaz veya yeniden `create()` edilmez.
- Kullanıcıya/çağırana dönen corruption mesajı snapshot içeriğini veya içindeki kişisel/gizli veriyi yansıtmaz.

Bu sınır yalnız persistence bütünlüğünü sertleştirir. Worker/model/UI'ya GoalState yazma yetkisi vermez; reducer/CAS otorite modeli, identity/audit koruması, terminal state ve atomic write kuralları değişmez.

## İlk gerçek cutover'dan önce zorunlu preflight kararları

### 1. Identity

Cutover bir job için tek canonical kimliği kesinleştirmeden başlayamaz:

- `owner` ve `job_id` legacy kayıtla bire bir eşleşmelidir.
- `goal` legacy `request` projection'ının anlamını değiştirmemelidir.
- `execution_mode` için compatibility katmanındaki sabit `agent` varsayımının cutover sonrası doğru olup olmadığı açıkça karara bağlanmalıdır; bu PR yeni eşleme varsaymaz.
- Aynı `owner + job_id` için birden fazla bağımsız canonical lifecycle kaydı oluşturulamaz.

### 2. Terminal state

- Canonical terminal state yalnız `done` ve `cancelled`dır.
- Terminal canonical state compatibility advance ile yeniden açılamaz.
- İlk cutover, legacy ve canonical terminal uyuşmazlığında hangi tarafın otorite olacağını ve işlemin fail-closed mu, reconcile mı olacağını ayrıca tanımlamadan etkinleştirilemez.
- `failed`, mevcut GoalState şemasında terminal değildir; cutover planı onu `done/cancelled` ile aynı kabul edemez.

### 3. Missing state

Aşağıdaki durumlar ayrı ayrı tanımlanmadan cutover yoktur:

- legacy var, canonical yok;
- canonical var, legacy yok;
- ikisi de var ama identity alanları uyuşmuyor;
- canonical dosya/şema geçersiz;
- legacy state mevcut projection tablosunda yok.

Bugünkü compatibility davranışında canonical yoksa `project(job)` ile oluşturulabilir; bilinmeyen legacy state reddedilir. Canonical authority cutover bu davranışı otomatik olarak kendi missing-state politikası sayamaz.

### 4. Legacy → canonical projection sınırı

Projection yalnız global lifecycle için gerekli canonical alanları taşır. Legacy journal'daki `goals`, `steps`, `outputs` ve diğer yürütme ayrıntıları GoalState identity/lifecycle alanlarına sıkıştırılmaz. Bunlar ileride ExecutionRecord sınırında ele alınır.

`approval_at` legacy runtime'da approval bekleme süresini takip eder ve mevcut akışta yaklaşık 120 saniyelik approval timeout kararına girdidir. Canonical GoalState şemasında bu alan yoktur. Gerçek cutover öncesinde `approval_at` ve benzeri yürütme-zamanı alanlarının GoalState dışında hangi ExecutionRecord/control sınırında yaşayacağı açıkça karara bağlanmalıdır; bu dokümantasyon runtime timeout semantiğini değiştirmez.

Projection'ın mevcut state eşleme tablosu ilk cutover için başlangıç kanıtıdır; yeni state eşlemesi kod ve test kanıtı olmadan dokümana eklenmez.

### 5. Rollback

İlk gerçek cutover geri dönüş planı olmadan etkinleştirilemez. Rollback sözleşmesi en az şunları belirlemelidir:

- hangi persistence kaydının cutover öncesi authority olduğu;
- cutover'ın hangi atomik sınırda açılıp kapandığı;
- başarısız canonical write/read sonrası legacy authority'ye güvenli dönüş koşulu;
- iki taraf farklı lifecycle state taşıyorsa sessiz overwrite yerine fail-closed/reconcile davranışı;
- terminal state'in rollback sırasında yeniden açılmaması.

Bugünkü save hook'taki byte-level compensation yalnız mevcut legacy-write compatibility akışının geri alma mekanizmasıdır; gelecekteki authority rollback sözleşmesinin yerine geçmez.

## Cutover öncesi geçiş kapısı

İlk runtime cutover PR'ı ancak aşağıdakileri açıkça kanıtladığında başlayabilir:

1. Identity eşleme ve collision davranışı tanımlı.
2. Terminal uyuşmazlık politikası tanımlı.
3. Missing/corrupt canonical ve missing legacy davranışı tanımlı.
4. Legacy → canonical projection kapsamı sabit ve testli.
5. Rollback/reconcile sınırı tanımlı.
6. ExecutionRecord ile GoalState sorumluluk ayrımı korunuyor; step/output/waiting/retry ayrıntıları GoalState'e doldurulmuyor.
7. Legacy write authority'nin hangi dar cutover noktasında sona ereceği ayrıca ve açıkça gösteriliyor.

Bu kapı geçilmeden canonical dosyanın varlığı veya compatibility sync'in çalışması, GoalState'in runtime write authority olduğu anlamına gelmez.

## Kapsam dışı

- `modules/goal_executor.py` değişikliği veya yeniden yazımı
- reducer/CAS otorite modeli değişikliği
- dual-write authority
- worker/effect/permission değişikliği
- yeni runtime/planner/subscription
- ExecutionRecord implementasyonu
- CI veya watcher değişikliği
