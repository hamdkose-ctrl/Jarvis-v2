# Jarvis Stage 0–4 Architecture Guard

**Durum:** Aşama 0–4 kapanış denetimi  
**Amaç:** Yeni kodun kabul edilmiş yürütme mimarisinden sapmasını PR aşamasında otomatik yakalamak.

Bu belge `docs/architecture/JARVIS_EXECUTION_ARCHITECTURE_V1.md` ve `docs/agents/gorev-cekirdegi.md` kararlarını otomatik denetim kurallarına indirger. Denetçi yeni planner, yeni state motoru veya yeni ürün davranışı icat etmez; yalnız mevcut sınırların ihlalini ve bilinen borçların durumunu raporlar.

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
- Worker, model, UI, watcher veya event kaynağı canonical state'i doğrudan değiştiremez.
- Stale/foreign sonuç state değiştiremez.

### Aşama 4 — WorkerResult / Event / Crash Recovery
- Durable WorkerResult exact fence taşır: owner, job, step, command, attempt, expected job version, capability version ve input digest.
- Conditional/reconciliation-required effect dış çağrıdan önce write-ahead intent kaydı ister.
- Intent var + receipt yok = `unknown`; blind retry yok, yalnız read-only reconcile.
- Verified receipt = `succeeded`; provider tekrar çağrılmaz.
- RuntimeEvent yalnız evidence üretir; global state kararı vermez.
- Non-durable convenience yolu conditional/yan etkili capability çalıştıramaz.

## Otomatik BLOCKER kuralları

### ARCH-001 — Yeni canonical CAS writer yasak
`goal_state_store.compare_and_swap(...)` yalnız mevcut canonical adapterlarda çağrılabilir:
- `modules/goal_state_compat.py`
- `modules/worker_result_commit.py`
- `modules/runtime_event_commit.py`

### ARCH-002 — DecisionContext'siz durable gate yasak
`runtime_execution_gate.plan_task(...)` production kodunda explicit DecisionContext olmadan çağrılamaz. Kabul edilen durable yol `_decision_context(job, step)` ile domain/user/job/effect alanlarını açıkça türetir. Generic `**kwargs` bu kuralı karşılamaz.

### ARCH-003 — Yeni doğrudan executor yasak
Yeni production modülü `goal_tools.execute(...)` çağırarak ikinci execution boundary oluşturamaz. Mevcut sınırlar:
- `modules/specialist_orchestrator.py`
- `modules/worker_result_hook.py`

## Otomatik WARNING backlog

### ARCH-W001 — RuntimeEvent production subscription
RuntimeEvent schema, freshness/dedup, persistent seen ve Reducer/CAS commit hazırdır; fakat gerçek production subscription producer henüz yoktur. `source_watch` yapay biçimde bir job'a bağlanmaz.

Kapanış şartı:

```text
Durable Job/Core
→ kalıcı subscription identity/lifecycle
→ watcher/source yalnız immutable RuntimeEvent
→ freshness/dedup/resume doğrulaması
→ runtime_event_commit
→ Reducer/CAS evidence
```

## Alias tespiti

ARCH-001/002/003, çağrıyı doğrudan `goal_tools.execute(...)` / `goal_state_store.compare_and_swap(...)` / `runtime_execution_gate.plan_task(...)` biçiminde görmekle sınırlı değildir. Denetçi her dosyada statik `import X as Y` ve `from X import Z as W` alias'larını AST üzerinden çözer ve aynı çağrıyı eşdeğer biçimlerde de yakalar:

- `from modules.goal_tools import execute as run_tool` → `run_tool(...)`
- `import modules.goal_tools as tools` → `tools.execute(...)`
- `from modules.goal_state_store import compare_and_swap as cas` → `cas(...)`
- `import modules.runtime_execution_gate as gate` → `gate.plan_task(...)`

Allowlist kontrolü değişmez: alias'lı çağrı da mevcut `_CAS_ALLOWLIST` / `_DIRECT_EXECUTE_ALLOWLIST` dosya yollarına göre değerlendirilir, yeni genel bir izin listesi açılmaz. `getattr`, `eval`, import hook gibi dinamik/analiz edilemeyen çözümleme yolları kapsam dışıdır — guard bunları çözmeye çalışmaz.

## Denetçinin kapsamı
`modules/architecture_guard.py` yalnız deterministik, statik olarak kanıtlanabilen kuralları BLOCKER yapar. Yoruma açık roadmap sapmaları ayrı ajan/insan incelemesiyle değerlendirilir. Static guard birim testinin, Windows acceptance'ın veya gerçek effect testinin yerine geçmez.

`modules.validation` bu guard'ı zorunlu çalıştırır. Böylece gelecek PR'larda mimari kaçak, aylar sonra yapılan geriye dönük taramaya bırakılmaz.
