# GoalState Cutover Gap Register v1

Durum: **karar öncesi, kaynak-doğrulanmış gap register**. Bu belge migration/cutover implementasyonu değildir; mevcut davranışı dört sınıfta ayırır: **KAPALI**, **KÜÇÜK HARDENING**, **CUTOVER BLOCKER**, **DEFERRED**.

Kaynak tabanı: `docs/architecture/GOALSTATE_CUTOVER_V1.md`, `modules/goal_state_save_hook.py`, `modules/goal_state_compat.py`, `modules/goal_state_store.py`, `modules/goal_executor.py`, `modules/core_state_reducer.py`, `tests/test_goal_state_persistence.py`, `tests/test_core_state_reducer.py`.

## Özet

- **KAPALI:** 8 madde
- **KÜÇÜK HARDENING:** 2 madde
- **CUTOVER BLOCKER:** 4 madde
- **DEFERRED:** 4 madde

Bu sayılar yalnız bu register'daki karar maddelerini sayar; yeni tasarım üretmez.

## Gap register

| Sınıf | Bulgu | Kaynak kanıtı | Cutover anlamı |
|---|---|---|---|
| **KAPALI** | Canonical sync hatasında legacy write sessizce devam etmez. | `modules/goal_state_save_hook.py::_atomic`: `synced = goal_state_compat.sync(job, canonical)` çağrısı legacy `_ORIGINAL_ATOMIC(path, data)` çağrısından **önce** ve legacy-write `try:` bloğunun dışındadır. `sync()` exception üretirse fonksiyon orada çıkar; legacy atomic'e ulaşılmaz. `tests/test_goal_state_persistence.py::test_goal_executor_save_is_fail_closed_when_canonical_sync_fails` ayrıca legacy/latest kaydının oluşmadığını kilitler. | Güvenlik davranışı fail-closed'dur; bu başlık migration blocker değildir. |
| **KÜÇÜK HARDENING** | Canonical sync failure fail-closed olsa da save-hook bu pre-legacy-sync exception için kendi diagnostic kaydını üretmez. | `modules/goal_state_save_hook.py::_atomic`: `_record_failure(...)` yalnız legacy `_ORIGINAL_ATOMIC()` başarısızlığının `except` bloğunda ve compensation hatasında çağrılır; `goal_state_compat.sync()` çağrısı bu bloktan öncedir. | Güvenlik açığı değil, observability/diagnostic boşluğudur. |
| **KAPALI** | Bilinmeyen legacy state fail-closed'dur. | `modules/goal_state_compat.py::_target`: `_STATE_MAP.get(...)` `None` ise `ValueError('Legacy job state GoalState ile eşlenemiyor.')`. `project()` ve `advance()` önce `_target()` kullanır. | Bilinmeyen state canonical olarak kabul edilmez. |
| **KÜÇÜK HARDENING** | `_STATE_MAP` drift'i güvenli biçimde fail-closed olur; ancak main'deki persistence testleri tüm mapped alt-state'leri tek parity matrisiyle kilitlemiyor. | `modules/goal_state_compat.py::_STATE_MAP` şu legacy state'leri kapsar: `running`, `approval`, `question`, `review`, `paused`, `interrupted`, `blocked`, `failed`, `done`, `cancelled`. Main'de `tests/test_goal_state_persistence.py::test_legacy_waiting_state_and_blocker_are_reduced_and_persisted` ve `test_terminal_canonical_state_is_not_reopened_by_legacy_projection` kısmi kapsama sağlar; bütün harita için tek regression matrisi yoktur. | Yeni bir legacy state unutulursa `sync()` exception ile kesilir ve save-hook legacy write'a geçmez; sessiz divergence yoktur. Eksik olan geniş parity test kapsamıdır. |
| **KAPALI** | `blocker/question` canonical blocker'a türetiliyor. | `modules/goal_state_compat.py::_blocker`: `job['blocker'] or job['question']`; `approval`→`LEGACY_APPROVAL`, `question`→`LEGACY_QUESTION`, diğerleri→`LEGACY_BLOCKED`. `advance()` blocker değişimini `set_blocker`, yok oluşunu `clear_blocker` ile reducer üzerinden uygular. `test_legacy_waiting_state_and_blocker_are_reduced_and_persisted` bunu doğrular. | Global lifecycle için blocker projection mevcut. |
| **KAPALI** | `approval/question/review/paused/interrupted/blocked` alt-state'leri canonical lifecycle'a bilinçli olarak daraltılıyor. | `modules/goal_state_compat.py::_STATE_MAP`: `approval/question`→`waiting`; `review/paused/interrupted/blocked`→`paused`. `GOALSTATE_CUTOVER_V1.md` aynı mapping'i preflight sınırı olarak belgeler. | Bu alanlar canonical GoalState'te ayrı state değildir; compatibility projection olarak türetilir. |
| **DEFERRED** | `created` canonical GoalState v1'e taşınmıyor. | `modules/goal_executor.py` yeni legacy job'da `created=time.time()` tutar; `modules/goal_state_compat.py::project` yalnız `owner`, `job_id`, `goal=request`, sabit `execution_mode='agent'` ile `goal_state.new()` çağırır. `GOALSTATE_CUTOVER_V1.md` execution ayrıntılarının ayrı ExecutionRecord sınırında ele alınacağını söyler. | Mevcut lifecycle authority için kaynakta zorunlu alan değildir; provenance/zaman bilgisi gerekiyorsa ayrı RFC/PR kararı gerekir. |
| **DEFERRED** | `approval_at` canonical GoalState v1'e taşınmıyor. | `modules/goal_executor.py::_record` approval çıktısında `job['approval_at']=time.time()` yazar; `control_key()` de bu alanı kullanır. `goal_state_compat.project/advance` bu alanı okumaz. | Approval TTL/UI kontrol bağlamıdır; global lifecycle state'e zorla eklenmemeli. ExecutionRecord/approval-control kararı ayrı RFC/PR'dır. |
| **CUTOVER BLOCKER** | `execution_mode` compatibility katmanında sabit `'agent'`; gerçek cutover için bunun otoriter mapping olduğu kararlaştırılmış değil. | `modules/goal_state_compat.py::project` doğrudan `execution_mode='agent'` geçirir. `GOALSTATE_CUTOVER_V1.md`, bu varsayımın cutover sonrası doğru olup olmadığının açıkça karara bağlanmasını zorunlu tutar. | Canonical identity alanı olduğu için authority cutover öncesi karar gerekir. |
| **CUTOVER BLOCKER** | Canonical/legacy authority geçiş noktası hâlâ belirlenmiş değil. | `GOALSTATE_CUTOVER_V1.md`: mevcut runtime'da legacy `goal_executor` JSON journal write authority; canonical yalnız compatibility projection/sync. `modules/goal_state_save_hook.py::_atomic` önce canonical sync, sonra legacy write yaparak bu geçici dual-write compatibility yönünü gösterir. | Gerçek cutover, hangi atomik sınırda legacy authority'nin sona ereceğini açıkça tanımlamadan başlayamaz. |
| **CUTOVER BLOCKER** | Missing-state ve authority uyuşmazlığı politikası tam cutover sözleşmesi olarak kapanmış değil. | `modules/goal_state_compat.py::sync`: canonical yoksa `project()`+`create()`, varsa `load()`+`advance()`+CAS. `GOALSTATE_CUTOVER_V1.md` özellikle legacy var/canonical yok, canonical var/legacy yok, identity mismatch ve authority uyuşmazlıklarının cutover öncesi ayrı karar istediğini belirtir. | Bugünkü compatibility davranışı gelecekteki canonical-authority missing-state politikası sayılamaz. |
| **CUTOVER BLOCKER** | Legacy ve canonical farklı lifecycle/terminal gerçeklik taşıdığında cutover authority/reconcile kuralı henüz tanımlı değil. | `modules/goal_state_compat.py::advance` canonical terminal ise mevcut state'i aynen döndürür. `GOALSTATE_CUTOVER_V1.md` terminal uyuşmazlığında hangi tarafın authority olacağı ve fail-closed/reconcile davranışının ayrıca tanımlanmasını ister. | Terminal reopen engeli kapalıdır; fakat authority conflict politikası gerçek migration blocker'ıdır. |
| **KAPALI** | Canonical terminal state legacy projection ile yeniden açılamaz. | `modules/goal_state_compat.py::advance`: `_target(job)` sonrası `if goal_state.terminal(current): return current`. `tests/test_goal_state_persistence.py::test_terminal_canonical_state_is_not_reopened_by_legacy_projection`. `tests/test_core_state_reducer.py` terminal mutation için `TerminalStateError` testleri içerir. | `done/cancelled` korunur. |
| **KAPALI** | CAS stale-writer, identity ve audit-prefix korumaları mevcut. | `modules/goal_state_store.py::compare_and_swap`: current version eşleşmezse conflict; `owner/job_id/goal/execution_mode` değişirse conflict; `next_state['audit']` current audit prefix'ini korumazsa conflict. `tests/test_goal_state_persistence.py::test_compare_and_swap_rejects_stale_persisted_version`; reducer tarafında `expected_version` ve audit üretimi `modules/core_state_reducer.py::apply/_audit` ile korunur. | Canonical write concurrency/integrity tabanı hazırdır. |
| **KAPALI** | Corrupt persisted canonical snapshot fail-closed ve overwrite edilmiyor. | `modules/goal_state_store.py::_decode_snapshot/load/compare_and_swap/compensate`; `PersistedStateCorruption`. `tests/test_goal_state_persistence.py`: truncated JSON, invalid UTF-8, schema-invalid JSON, corrupt CAS ve compensation testleri. | Corrupt-state hardening kapanmıştır; auto-reset yoktur. |
| **KAPALI** | Legacy write failure canonical değişikliği compensate ediyor. | `modules/goal_state_save_hook.py::_atomic`: legacy `_ORIGINAL_ATOMIC` exception'ında `goal_state_store.compensate(canonical, expected_state=synced, previous_bytes=before)`. `tests/test_goal_state_persistence.py::test_goal_executor_save_rolls_back_new_canonical_when_legacy_write_fails` ve `test_goal_executor_save_restores_previous_canonical_when_legacy_update_fails`. | Mevcut dual-write compatibility akışının byte-level rollback'ı korunur. |
| **KAPALI** | Owner namespace/id doğrulaması projection sınırında mevcut. | `modules/goal_state_save_hook.py::_legacy_job`: dosya adı 16-hex job id ile eşleşmeli; payload `id` path id ile eşleşmeli; `path.parent.name == owner` şartı var. `tests/test_goal_state_persistence.py::test_foreign_legacy_owner_never_projects_canonical_goalstate`. | Başka owner namespace'indeki legacy-shaped JSON canonical authority kazanmaz. |
| **KAPALI** | Aynı legacy snapshot için basic idempotency mevcut. | `modules/goal_state_compat.py::sync`: `advance()` sonrası version değişmediyse current döner, CAS yapmaz. `tests/test_goal_state_persistence.py::test_legacy_projection_is_idempotent_for_same_state`. | Aynı state tekrarı canonical version/audit'i gereksiz büyütmez. |
| **DEFERRED** | RuntimeEvent production subscription bu migration'ın parçası değildir. | `GOALSTATE_CUTOVER_V1.md` scope dışına `new runtime/planner/subscription` koyar; bu register kaynaklarında GoalState cutover için RuntimeEvent subscription gereksinimi yoktur. | Ayrı RFC/PR gerekir; cutover gap register'a blocker olarak eklenmez. |
| **DEFERRED** | Worker/effect alanları ve ExecutionRecord ayrıntıları GoalState cutover'a zorla bağlanmaz. | `GOALSTATE_CUTOVER_V1.md`: `goals/steps/outputs`, waiting/retry ve yürütme ayrıntıları GoalState lifecycle'a sıkıştırılmaz; ExecutionRecord ayrı sınırdır. Worker/effect/permission değişikliği scope dışıdır. | Ayrı RFC/PR; bu migration'ın blocker listesine dahil edilmez. |

## Alan eşleme özeti

| Legacy alan/durum | Canonical karşılığı | Durum | Sınıf | Kaynak |
|---|---|---|---|---|
| `created` | Yok | Kayıp; lifecycle için bugün kullanılmıyor | **DEFERRED** | `goal_executor` job creation; `goal_state_compat.project` |
| `approval_at` | Yok | Kayıp; approval TTL/control bağlamı | **DEFERRED** | `goal_executor._record`, `control_key`; `goal_state_compat` okumuyor |
| `blocker` / `question` | `blocker {code,text}` | Türetilmiş | **KAPALI** | `goal_state_compat._blocker/advance` |
| `approval` / `question` | `waiting` | Türetilmiş lifecycle | **KAPALI** | `_STATE_MAP` |
| `review` / `paused` / `interrupted` / `blocked` | `paused` | Türetilmiş lifecycle | **KAPALI** | `_STATE_MAP` |
| `execution_mode` | Sabit `agent` | Canonical identity'de var, legacy'den türetilmiyor | **CUTOVER BLOCKER** | `goal_state_compat.project`; `GOALSTATE_CUTOVER_V1.md` |

## Karar notu

Bugünkü kaynakta **“sync hata verince legacy write sessizce devam ediyor” iddiası doğru değildir**. Akış sırası nettir: `_legacy_job` kabulü → canonical path/before bytes → `goal_state_compat.sync()` → ancak başarılıysa legacy `_ORIGINAL_ATOMIC()`. Dolayısıyla sync failure güvenlik açısından fail-closed'dur. Açık küçük iş, bu pre-legacy-sync hatasının save-hook seviyesinde diagnostic/observability kaydının olmamasıdır.

Gerçek cutover öncesi burada blocker olarak kalanlar; execution-mode identity kararı, authority cutover noktası, missing-state/authority mismatch politikası ve legacy-vs-canonical lifecycle/terminal conflict politikasıdır. Bu belge bunlar için yeni migration tasarımı önermez.

## ExecutionRecord v1 (2026-10-25)

Legacy JSON yazımını durdurmanın ön koşulu olarak `goals/steps/outputs` ve executor'ın kendi ilerleme alanları ayrı bir kayda taşındı: `modules/execution_record.py`, dosya `<id>.execution.json`. GoalState şeması değişmedi; canonical yalnız lifecycle taşımaya devam eder.

- Yazım: `goal_state_save_hook._atomic` sırası artık canonical sync → ExecutionRecord → legacy journal. ExecutionRecord yazılamazsa canonical compensate edilir ve legacy'ye geçilmez; legacy yazılamazsa ExecutionRecord önceki baytlarına döner (yoksa silinir) ve canonical compensate edilir.
- Okuma: `goal_executor.latest`, `web_tasks.team_verify` ve `team_center.snapshot` önce ExecutionRecord'u okur; ExecutionRecord'u olmayan eski işler için legacy `<id>.json` geri dönüş yoludur.
- Kalan adım (ayrı PR): legacy `<id>.json` yazımının save hook'tan kaldırılması ve `goalstate_cutover_preflight`'ın ExecutionRecord'u tanıması.
