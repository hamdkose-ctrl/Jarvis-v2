# Jarvis Stage 0–4 Architecture Guard

**Durum:** Aşama 0–4 kapanış denetimi  
**Amaç:** Yeni kodun kabul edilmiş yürütme mimarisinden sapmasını PR aşamasında otomatik yakalamak.

Bu belge `docs/architecture/JARVIS_EXECUTION_ARCHITECTURE_V1.md`, `docs/architecture/JARVIS_UI_CORE_BOUNDARY.md` ve `docs/agents/gorev-cekirdegi.md` kararlarını otomatik denetim kurallarına indirger. Denetçi yeni planner, yeni state motoru veya yeni ürün davranışı icat etmez; yalnız mevcut sınırların ihlalini ve bilinen borçların durumunu raporlar.

## Sonuç seviyeleri

- `BLOCKER`: Mekanik olarak kanıtlanmış mimari ihlal. Validation kırılır, merge edilmez.
- `WARNING`: Bilinçli ertelenmiş veya henüz tamamlanmamış mimari borç. Validation geçebilir ama uyarı görünür kalır.

## Aşama 0–4 değişmezleri

### Aşama 0 — Tek omurga
- Fast/Agent/Durable ayrı execution motorları değildir.
- Yeni özellik ikinci görev/state/permission/retry/evidence motoru açamaz.
- Worker global `done/waiting/failed` otoritesi değildir.

### Aşama 1 — Capability Manifest
- Manifest statik politika/şema kaynağıdır; ikinci dispatcher değildir.
- Callable binding mevcut worker/dispatcher katmanında kalır.
- Replay/effect/reconciliation bilgisi capability politikasından türetilir.

### Aşama 2 — Decision / Permission / Effect

```text
Domain invariant → Decision Authority → Permission → Effect Policy → Worker
```

- Durable runtime gate gerçek DecisionContext olmadan çağrılamaz.
- `pass + execute + allow + ready` dışındaki karar Worker'a ulaşamaz.
- Permission yan etkiden hemen önce yeniden değerlendirilir.

### Aşama 3 — GoalState / Reducer / CAS
- Canonical GoalState'in mantıksal write authority'si Core State Reducer'dır.
- Canonical mutation yalnız izinli commit/compat adaptörleri üzerinden CAS ile yapılır.
- Canonical storage writer'ları da statik olarak sabittir: `create` yalnız compat, `compare_and_swap` yalnız onaylı commit adaptörleri, `compensate` yalnız save hook rollback yolu (ARCH-001/004/005).
- Worker, model, UI, watcher veya event kaynağı canonical state'i doğrudan değiştiremez.
- Stale/foreign sonuç state değiştiremez.

Storage writer kuralları "tek writer / tek Core / tek Reducer" hedefini mekanik olarak destekler: yeni bir modülün kendi başına projection üretmesi, state'i overwrite etmesi veya başarısız yazımı kendi geri-yazması ile düzeltmesi PR aşamasında blocker olur. Bu, mimari ihlali statik olarak kanıtlar; GoalState'in runtime davranışını (doğru state geçişi, race/stale sonucu, recovery doğruluğu) kanıtlamaz. O doğrulama ayrı runtime/acceptance testlerinin işidir.

### Aşama 4 — WorkerResult / Event / Crash Recovery
- Durable WorkerResult exact fence taşır: owner, job, step, command, attempt, expected job version, capability version ve input digest.
- Conditional/reconciliation-required effect dış çağrıdan önce write-ahead intent kaydı ister.
- Intent var + receipt yok = `unknown`; blind retry yok, yalnız read-only reconcile.
- Verified receipt = `succeeded`; provider tekrar çağrılmaz.
- RuntimeEvent yalnız evidence üretir; global state kararı vermez.
- Non-durable convenience yolu conditional/yan etkili capability çalıştıramaz.

### UI / Core business authority sınırı

UI presentation ve interaction katmanıdır. Kullanıcı girdisini canonical backend/Core'a iletir ve dönen state/evidence/result bilgisini gösterir. UI; provider fallback, permission ALLOW/DENY, GoalState lifecycle, Finance risk/decision, source conflict, worker routing, completion, scheduler veya execution authority tanımlayamaz.

Backend state'ine göre düğme/renk/icon/loading göstermek presentation'dır. Ancak bir lifecycle/approval isteğinin gerçekten geçerli olup olmadığına UI'nın karar vermesi business authority'dir. Presentation-only özellikler dışında Definition of Done sorusu şudur:

> Bu feature'ın mevcut UI katmanı tamamen silinse backend/core davranışı ve canonical sonucu yaşamaya devam eder mi?

Cevap "hayır" ise sınır ihlalidir. Ayrıntı ve 0–4 audit kaydı `docs/architecture/JARVIS_UI_CORE_BOUNDARY.md` içindedir.

## Otomatik BLOCKER kuralları

### ARCH-001 — Yeni canonical CAS writer yasak
`goal_state_store.compare_and_swap(...)` yalnız mevcut canonical adapterlarda çağrılabilir:
- `modules/goal_state_compat.py`
- `modules/worker_result_commit.py`
- `modules/runtime_event_commit.py`

### ARCH-004 — Yeni canonical GoalState create writer yasak
`goal_state_store.create(...)` canonical GoalState'in ilk projection yazımıdır. Bu yüzden yalnız tek dosyada kabul edilir:
- `modules/goal_state_compat.py`

Başka hiçbir production modülünün (commit adaptörleri dahil) doğrudan `create` çağırması BLOCKER'dır; yeni projection yolu compat üzerinden açılır.

### ARCH-005 — Yeni canonical GoalState compensate writer yasak
`goal_state_store.compensate(...)` legacy write başarısızlığında geri alma (rollback) yoludur. Yalnız tek dosyada kabul edilir:
- `modules/goal_state_save_hook.py`

Compensate'i başka bir yerden çağırmak, Reducer'ın write otoritesinin yanına ikinci bir geri-yazma otoritesi koyduğu için BLOCKER'dır.

Üç kuralın allowlist'i ayrıdır ve birbirine izin vermez: `worker_result_commit.py` / `runtime_event_commit.py` CAS çağırabilir ama `create` veya `compensate` çağıramaz; `goal_state_save_hook.py` compensate çağırabilir ama CAS çağıramaz. Yeni bir writer gereksinimi allowlist'i genişleterek değil, compat/commit adaptörünün kendisiyle birlikte ayrıca onaylanarak çözülür.

### ARCH-002 — DecisionContext'siz durable gate yasak
`runtime_execution_gate.plan_task(...)` production kodunda explicit DecisionContext olmadan çağrılamaz. Kabul edilen durable yol `_decision_context(job, step)` ile domain/user/job/effect alanlarını açıkça türetir. Generic `**kwargs` bu kuralı karşılamaz.

### ARCH-003 — Yeni doğrudan executor yasak
Yeni production modülü `goal_tools.execute(...)` çağırarak ikinci execution boundary oluşturamaz. Mevcut sınırlar:
- `modules/specialist_orchestrator.py`
- `modules/worker_result_hook.py`

### ARCH-007 — WorkerResult wrapper Decision Authority'yi bypass edemez

`worker_result_hook.execute(...)` çağrısı WorkerResult fence üretse de kendi içinde doğrudan `goal_tools.execute(...)` çalıştırır; tek başına DecisionContext veya `runtime_execution_gate.plan_task(...)` kararı üretmez. Bu yüzden wrapper'ın production caller'ı yalnız durable gate'i önce uygulayan:

- `modules/specialist_orchestrator.py`

olabilir. Başka bir production modülünün (scheduler/session/memory dahil) `worker_result_hook.execute(...)` çağırması, doğrudan `goal_tools.execute(...)` çağrısını gizleyerek ikinci execution boundary oluşturabileceği için `ARCH-007 BLOCKER`dır. Çözüm allowlist'i genişletmek değil, çağrıyı mevcut durable orchestrator/Core hattına taşımaktır.

### ARCH-006 — UI yeni business-authority dependency alamaz

`web.py`, `web_*.py`, `gui.py` ve `launcher.py` UI/bridge/shell yüzeyleri AST üzerinden `modules.*` dependency edge'leri için taranır. Yeni bir UI dosyasının Core authority internallerine doğrudan import bağımlılığı BLOCKER'dır. Korunan authority aileleri arasında GoalState/Reducer writer'ları, goal/task executor internalleri, permission/decision authority, completion ve runtime commit/gate katmanları vardır.

Bu kontrol function/message keyword taraması değildir. `import modules.goal_executor as goals` veya `from modules import goal_executor` aynı dependency edge'i olarak görülür. UI'nın `ui_jobs`, status/query veya configuration servisi gibi presentation-facing servislere bağımlılığı bu kuralla otomatik olarak yasaklanmaz.

Yeni UI ihtiyacı Core'da olmayan bir karar gerektiriyorsa çözüm allowlist büyütmek değildir; ilgili domain/Core'da canonical facade/service oluşturmak veya mevcut sözleşmeyi genişletmektir.

## Otomatik WARNING backlog

### ARCH-W001 — RuntimeEvent production subscription (kapandı, 26 Ekim 2026, Faz 2-2)
RuntimeEvent schema, freshness/dedup, persistent seen ve Reducer/CAS commit hattına gerçek üretici `modules/runtime_subscription.py` ile bağlandı (`source_watch` ve olay webhook'u). Kaynak takibini ekleyen hedef `bind_job` ile aboneliğin sahibidir; sahibi olmayan kaynak için `ensure_source` ayrı bir kaynak GoalState'i açar. Uyarı, `modules/` altında production `runtime_event_commit.commit` çağrısı kalmazsa yeniden çıkar.

Kapanış şartı (karşılandı):

```text
Durable Job/Core
→ kalıcı subscription identity/lifecycle
→ watcher/source yalnız immutable RuntimeEvent
→ freshness/dedup/resume doğrulaması
→ runtime_event_commit
→ Reducer/CAS evidence
```

### ARCH-W003 — UI/Core authority baseline (aktif borç yok)

İlk auditte `web_tasks.py` içindeki goal/task control ve verification akışlarının Core authority internallerine doğrudan dependency taşıdığı doğrulandı ve exact `path + module dependency` baseline olarak WARNING seviyesinde donduruldu.

- #441 `team_control` lifecycle/approval authority'yi `modules/team_control_service.py` Core servisine taşıdı.
- #444 `team_verify` job/output seçimi ve verification toplama mantığını `modules/team_verify_service.py` read-only Core sorgu servisine taşıyor.
- #444 branch'inde `web_tasks.py` için `_UI_AUTHORITY_BASELINE` boştur. Eski `goal_executor`, `goal_tools`, `task_agents`, `task_results` veya `execution_record` dependency edge'lerinden biri UI'ya geri eklenirse artık `ARCH-W003` WARNING değil, `ARCH-006` BLOCKER oluşur.

`ARCH-W003` mekanizması yalnız gelecekte ayrıca kabul edilmiş, exact bir geçici borç açıkça baseline'a alınırsa kullanılır; mevcut `web_tasks.py` borcuna genel izin vermez. #444 exact-head CI ve gerçek PC watcher kabulü gelmeden bu migration tamamlandı sayılmaz.

## Alias tespiti

ARCH-001/002/003/004/005/007, çağrıyı doğrudan `goal_tools.execute(...)` / `worker_result_hook.execute(...)` / `goal_state_store.compare_and_swap(...)` / `runtime_execution_gate.plan_task(...)` / `goal_state_store.create(...)` / `goal_state_store.compensate(...)` biçiminde görmekle sınırlı değildir. Denetçi her dosyada statik `import X as Y` ve `from X import Z as W` alias'larını AST üzerinden çözer ve aynı çağrıyı eşdeğer biçimlerde de yakalar:

- `from modules.goal_tools import execute as run_tool` → `run_tool(...)`
- `import modules.goal_tools as tools` → `tools.execute(...)`
- `import modules.worker_result_hook as hook` → `hook.execute(...)`
- `from modules.goal_state_store import compare_and_swap as cas` → `cas(...)`
- `import modules.runtime_execution_gate as gate` → `gate.plan_task(...)`
- `from modules.goal_state_store import create as make` → `make(...)`
- `import modules.goal_state_store as store` → `store.compensate(...)`

Allowlist kontrolü değişmez: alias'lı çağrı da ilgili kuralın `_CAS_ALLOWLIST` / `_CREATE_ALLOWLIST` / `_COMPENSATE_ALLOWLIST` / `_DIRECT_EXECUTE_ALLOWLIST` / `_WORKER_RESULT_EXECUTE_ALLOWLIST` dosya yollarına göre değerlendirilir, yeni genel bir izin listesi açılmaz. `getattr`, `eval`, import hook gibi dinamik/analiz edilemeyen çözümleme yolları kapsam dışıdır — guard bunları çözmeye çalışmaz.

ARCH-006 için alias çözmek ayrıca gerekmez: import'un canonical module dependency edge'i doğrudan AST düğümünden çıkarılır; yerel alias adı boundary sonucunu değiştirmez.

## Denetçinin kapsamı
`modules/architecture_guard.py` yalnız deterministik, statik olarak kanıtlanabilen kuralları BLOCKER yapar. Yoruma açık roadmap sapmaları ayrı ajan/insan incelemesiyle değerlendirilir. Static guard birim testinin, Windows acceptance'ın veya gerçek effect testinin yerine geçmez.

`modules.validation` bu guard'ı zorunlu çalıştırır. Böylece gelecek PR'larda mimari kaçak, aylar sonra yapılan geriye dönük taramaya bırakılmaz.

