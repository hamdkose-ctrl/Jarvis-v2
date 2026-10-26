# Jarvis Program Ledger v1

Durum: **program/handoff defteri**. Bu belge canlı PR listesi değildir; ajan değişse bile Jarvis programının kararlarını, sırasını ve devralma kurallarını tek yerde tutar. GitHub’daki güncel PR/branch/SHA durumu her zaman canlı otoritedir.

## 1. Kullanım kuralı

Her ajan yeni işe başlamadan önce şu sırayı uygular:

1. `git fetch origin` çalıştırır ve güncel `origin/main` SHA’sını doğrular.
2. GitHub’daki **açık PR listesini** okur; aynı işin, dalın veya head SHA’nın zaten açık/merge edilmiş olup olmadığını kontrol eder.
3. Bu ledger’ı okur.
4. İlgili mimari sözleşme ve testleri okur.
5. Ancak bundan sonra yeni branch/iş açar.

Kurallar:

- Aynı iş/branch/commit daha önce merge edilmiş mi kontrol edilmeden yeni görev açılmaz.
- Dal başlangıç noktası güncel `origin/main` olmalıdır. `git diff --stat origin/main` silme gösteriyorsa dal bayattır; bu fark gerçek işten değil, dalın hiç görmediği merge’lerden gelir. Bayat dal PR’a açılmaz, `--force`/rebase ile de zorlanmaz; `origin/main`’den yeni dal açılır.
- GitHub PR durumu canlı otoritedir; bu belge anlık PR numaralarını kalıcı gerçek gibi tutmaz.
- Bu ledger karar ve yol haritası otoritesidir. Canlı uygulama durumu için GitHub; mimari karar/sıra için bu ledger + referans verilen sözleşmeler okunur.
- Bir PR bu ledger’daki karar/sırayı değiştiriyorsa merge sonrası ledger güncellemesi ayrıca değerlendirilir.
- Eski veya superseded sohbet/PR notu, güncel kaynak ve GitHub durumunun önüne geçmez.

## 2. Kilitli mimari

Aşağıdaki sınırlar program boyunca değişmez kabul edilir; aksi ancak ayrı mimari RFC ile ele alınır:

- **Core tek authority’dir.** Planner/model/worker/watcher/UI/external agent yalnız proposal/result/event üretir; global lifecycle ve completion kararı Core’dadır. Kaynak: `docs/architecture/JARVIS_STAGE_0_4_GUARD.md`, `docs/architecture/JARVIS_EXECUTION_ARCHITECTURE_V1.md`.
- **Worker yalnız WorkerResult/evidence döndürür.** Worker `succeeded` dese bile global `done` değildir. Fence alanları kabul edilmeden sonuç state’e işlenmez. Kaynak: `modules/worker_result.py`, `modules/worker_result_commit.py`.
- **GoalState yalnız Reducer/CAS üzerinden ilerler.** Worker/model/UI/watcher doğrudan canonical state yazamaz. Stale version, identity ve audit-prefix korunur. Canonical storage mutation API’lerinin her biri ayrı dosya allowlist’ine bağlıdır ve allowlist’ler birbirine izin vermez: `create` yalnız `goal_state_compat`, `compare_and_swap` yalnız onaylı commit adaptörleri (`goal_state_compat`, `worker_result_commit`, `runtime_event_commit`), `compensate` yalnız `goal_state_save_hook` rollback yolu. Kaynak: `modules/core_state_reducer.py`, `modules/goal_state_store.py`, `modules/architecture_guard.py` (ARCH-001/004/005), `docs/architecture/JARVIS_STAGE_0_4_GUARD.md`.
- **Canonical sync başarısızsa işlem orada durur.** Save-hook önce canonical sync, sonra legacy write yapar; `goal_state_compat.sync()` hatası yutulmaz, legacy write ve compensation hiç başlamaz, hiçbir dosyada otomatik repair yapılmaz. Hata kendi tanı noktasıyla (`_atomic:canonical_sync`) legacy-write ve compensation kayıtlarından ayrıştırılır. Kaynak: `modules/goal_state_save_hook.py`, `docs/architecture/GOALSTATE_CUTOVER_GAP_REGISTER_V1.md`.
- **Karar sırası:** Domain invariant → Decision Authority → JIT Permission → Effect Policy → Worker. Permission/effect kararları worker’dan önce ve gerektiğinde yan etkiden hemen önce tekrar doğrulanır. Kaynak: `modules/runtime_execution_gate.py`, `modules/permission_gate.py`, capability manifest sözleşmeleri.
- **Effect/crash recovery:** journal-required effect dış çağrıdan önce durable intent ister; intent var/receipt yoksa `unknown`, blind retry yok, yalnız read-only reconcile. Receipt olsa bile global completion değildir. Kaynak: `modules/effect_journal.py`, `modules/crash_recovery.py`, `modules/effect_recovery_runtime.py`, `docs/architecture/JARVIS_EFFECTFUL_WORKER_JOURNAL_MATRIX_V1.md`.
- **Hermes/external agent ikinci Core değildir.** Yalnız adapter/worker adayıdır; kendi planner/engine/permission/state otoritesini Jarvis Core’un yerine koyamaz. Kaynak: `docs/architecture/JARVIS_HERMES_ADAPTER_BOUNDARY_V1.md`, `docs/architecture/JARVIS_EXTERNAL_SKILL_ADOPTION_V1.md`.

## 3. Tamamlanan temel

Bu bölüm “program temeli mevcut” anlamına gelir; her madde ayrı acceptance/ürün kapsamı iddiası değildir.

| Temel | Kaynak-doğrulanmış durum | Referans |
|---|---|---|
| Aşama 0–4 ana omurga | Tek execution spine, manifest, decision/permission/effect sırası, GoalState Reducer/CAS, WorkerResult fence ve crash-recovery sınırları kaynakta tanımlı ve Architecture Guard ile korunuyor. | `docs/architecture/JARVIS_STAGE_0_4_GUARD.md`, `modules/architecture_guard.py`; mimari/guard PR türü |
| JarvisBench v0 + fixture schema | Deterministik read-only evaluator, v0 case kataloğu ve observation fixture şeması mevcut; canlı acceptance yerine geçmez. | `modules/jarvis_bench.py`, `docs/architecture/JARVIS_BENCH_V0.md`, `tests/test_jarvis_bench.py`; benchmark/fixture PR türü |
| Provider structured failures | Provider/runtime hataları için stabil `reason_code` ve `recovery_class` üretimi goal failure sonucuna bağlanmış; raw provider secret kullanıcı metnine taşınmamalı. | `modules/failure_policy.py`, `modules/goal_executor.py`, `tests/test_goal_failure_policy.py`; provider-resilience PR türü |
| Effect journal manifest coverage | `conditional + required` capability’lerde intent/receipt/reconcile kuralı tanımlı; blind retry yasak. | `modules/capability_manifest.py`, `modules/effect_recovery_runtime.py`, `docs/architecture/JARVIS_EFFECTFUL_WORKER_JOURNAL_MATRIX_V1.md`; effect-journal contract PR türü |
| Architecture Guard | Statik BLOCKER kuralları: ARCH-000 okunamayan modül, ARCH-001 canonical CAS, ARCH-002 DecisionContext’siz durable gate, ARCH-003 ikinci direct executor, ARCH-004 canonical `create`, ARCH-005 canonical `compensate`. Alias (`import X as Y`, `from X import Z as W`) çağrılarını da AST üzerinden çözer; dinamik `getattr`/`eval`/import hook kapsam dışı. ARCH-W001/W002 görünür backlog; `modules.validation` guard’ı zorunlu çalıştırır. | `modules/architecture_guard.py`, `tests/test_architecture_guard.py`, `docs/architecture/JARVIS_STAGE_0_4_GUARD.md`; architecture-guard PR türü |
| Persisted GoalState corruption hardening | Bozuk UTF-8/JSON/şema snapshot’ı kararlı corruption sınırında fail-closed; CAS/compensation bozuk snapshot üzerine sessizce yazmaz. | `modules/goal_state_store.py`, `tests/test_goal_state_persistence.py`; persistence-hardening PR türü |
| Dual-write parity testleri | Legacy→canonical state/blocker/terminal/idempotency/rollback parity’si persistence testleriyle karakterize edilmiş; bu gerçek cutover değildir. | `modules/goal_state_compat.py`, `modules/goal_state_save_hook.py`, `tests/test_goal_state_persistence.py`; compatibility/parity PR türü |
| Canonical sync failure observability | Save-hook, legacy write’a geçmeden önceki `sync()` hatasında ayrı tanı noktası üretiyor, aynı exception’ı yeniden fırlatıyor; legacy write/compensation çağrılmıyor, canonical byte değişmiyor. PR #305. | `modules/goal_state_save_hook.py`, `tests/test_goal_state_persistence.py`; observability PR türü |
| Salt-okunur cutover preflight checker | Owner dizinini olduğu gibi okur, değiştirmeden tarar; `OK`, `INVALID_LEGACY_RECORD`, `UNKNOWN_LEGACY_STATE`, `MISSING_CANONICAL`, `CANONICAL_CORRUPT`, `IDENTITY_MISMATCH`, `STATE_DIVERGENCE`, `TERMINAL_DIVERGENCE` reason kodlarını döndürür. Dosya yazmaz, CAS/create/compensate çağırmaz, repair yapmaz. PR #306. Bu aracın `OK` üretmesi cutover’ın yapıldığı anlamına gelmez; yalnız “güvenli mi?” sorusuna cevap verir. | `modules/goalstate_cutover_preflight.py`, `tests/test_goalstate_cutover_preflight.py`, `docs/architecture/GOALSTATE_CUTOVER_PREFLIGHT_V1.md`; preflight-tool PR türü |
| Canonical authority RFC | Dört cutover blocker’ı (execution_mode mapping, authority flip noktası, missing-state/identity, state/terminal uyuşmazlığı) için somut seçenekler, önerilen kararlar, kabul kriterleri, rollback sınırları ve gereken testler yazılı. PR #307. Karar 1, 3 ve 4 kabul edildi; Karar 2 kabul edildi, uygulaması kısmi (yalnız `authority` işaretleme, PR #313; legacy yazımın durması ayrı PR). | `docs/architecture/GOALSTATE_CANONICAL_AUTHORITY_RFC_V1.md`; authority-rfc PR türü |
| Operator onaylı cutover runner | RFC kararlarını guard tablosu olarak uygular: salt-okunur `plan()` + parmak izi, yalnız `MISSING_CANONICAL` için operatör onaylı tek seferlik backfill (`authority='legacy'`), owner genelinde fail-closed blocker, plan drift ve yazım sonrası doğrulama. Sync/save-hook'a bağlı değildir; legacy yazımı durdurmaz. | `modules/goalstate_cutover_runner.py`, `tests/test_goalstate_cutover_runner.py`, `docs/architecture/GOALSTATE_CUTOVER_RUNNER_V1.md`; cutover-runner PR türü |

## 4. Mevcut aktif şerit

**Aktif şerit: GoalState canonical cutover hazırlığı. Gerçek cutover henüz yapılmadı.**

Kaynak: `docs/architecture/GOALSTATE_CUTOVER_V1.md`, `docs/architecture/GOALSTATE_CUTOVER_GAP_REGISTER_V1.md`, `docs/architecture/GOALSTATE_CUTOVER_PREFLIGHT_V1.md`, `docs/architecture/GOALSTATE_CANONICAL_AUTHORITY_RFC_V1.md`. Bugünkü runtime’da legacy `goal_executor` JSON journal write authority olarak kalır; canonical GoalState compatibility projection/sync katmanıdır.

Cutover’a geçmeden önce sıra (durum güncel `main` kaynaklarından doğrulanmıştır; canlı merge durumu GitHub’dadır):

1. **Sync observability hardening — kapandı.** Canonical sync hatası kendi tanı noktasıyla görünür, hata yutulmuyor, legacy write/compensation başlamıyor.
2. **Canonical storage writer guard — kapandı.** `create`/`compare_and_swap`/`compensate` ayrı allowlist’lerle statik BLOCKER; ikinci projection veya geri-yazma otoritesi PR aşamasında yakalanıyor.
3. **Read-only preflight checker — kapandı.** Identity/missing/corrupt/divergence/terminal sınıfları değiştirmeden raporlanıyor.
4. **Authority RFC — belge olarak kapandı.** Dört blocker için seçenekler, önerilen kararlar, kabul kriterleri ve rollback sınırları yazılı.
5. **RFC kararlarının kabulü — kapandı.** Karar 1, 3, 4 kabul; Karar 2 kabul (flip noktası = job yaratılışı), uygulaması kısmi. Kabul notları RFC belgesindedir.
6. **Operator onaylı cutover runner — PR'da.** Kabul edilmiş kararları guard olarak uygular; yalnız operatör elle çalıştırır. Açık kalan: legacy JSON yazımının durdurulması (Karar 2'nin pratik sonucu) ve legacy-terminal/canonical-aktif kayıtların takibi.
7. **Yalnız kabul edilmiş migration planı** üzerinden uygulama PR’ları açılmalı.

Bu aşamada “canonical dosya var”, “compat sync çalışıyor” veya “preflight `OK` verdi” demek cutover tamamlandı anlamına gelmez.

## 5. Sıradaki iş sırası

Program sırası şudur:

1. Küçük GoalState hardening işleri — **kapanmış adımlar** (writer guard, sync observability, corruption sertliği, parity testleri).
2. Salt-okunur preflight checker ve testleri — **kapanmış adım**.
3. Authority RFC / cutover karar sözleşmesi — belge **yazıldı**, kararlar **kabul edildi** (Karar 2 uygulaması kısmi).
4. Kabul edilmiş migration karar/uygulama PR’ları — **açık adım**; ilki operator onaylı cutover runner.
5. Final Stage 0–4 acceptance: Architecture Guard BLOCKER=0, full `modules.validation`, current merged main SHA üzerinde gerekli Windows/PC acceptance ve temsilî durable E2E kanıtı.
6. **Ancak bundan sonra** read-only worker/Hermes pilotları ve capability-adoption deneyleri.

Bu sıra, aktif PR’ların merge sırası değildir; canlı mergeability/CI için GitHub kontrol edilir. Bir adım kaynakta zaten merge edilmişse yeniden yapılmaz, sonraki açık adıma geçilir.

## 6. Bilinçli ertelenenler

| Deferred konu | Neden şimdi değil? | Ne zaman yeniden açılır? |
|---|---|---|
| ~~RuntimeEvent durable subscription/producer~~ | Kapandı (26 Ekim 2026, Faz 2-2): `modules/runtime_subscription.py` kalıcı abonelik + `source_watch`/webhook üreticisi (#374), hedef sahipliği `bind_job` ile; ARCH-W001 temiz. Ayrıntı: `docs/roadmap-runtime-event-subscription-notu.md`. | Yeni olay kaynağı (webhook/queue) eklenince aynı abonelik modeline bağlanır. |
| ExecutionRecord ayrıntıları | Step/output/waiting/retry gibi yürütme ayrıntıları GoalState global lifecycle’a doldurulmamalı. | Canonical authority RFC, hangi verinin GoalState dışında kalacağını kesinleştirince ayrı ExecutionRecord RFC/PR olarak. |
| `created` / `approval_at` canonical taşıma kararı | `created` provenance; `approval_at` yaklaşık 120 sn approval timeout/control bağlamı taşır. Bunları GoalState’e zorla eklemek doğru kabul edilmedi. | Authority/ExecutionRecord sınırı kabul edilince; approval timeout’un kalıcı sahibi açıkça tanımlanınca. |
| Gerçek worker/product capability genişlemesi | Core güvenlik ve cutover şeridi bitmeden yeni capability’ler ikinci motor/otorite riski yaratabilir. | Final Stage 0–4 acceptance tamamlandıktan sonra, read-only benchmark → adapter → manifest → evidence/receipt kabul hattıyla. |

Hermes/external skill genişlemesi de bu son satırın içindedir; önce read-only pilot, sonra ayrı effectful kabul sözleşmesi gerekir.

## 7. PR / handoff kontrol listesi

Her PR öncesi ve devralmada şu kontrol yapılır:

- Aynı iş daha önce merge edilmiş mi? `main`, kapalı/merge edilmiş PR ve commit geçmişi kontrol edildi mi?
- İzinli dosyalar mevcut açık PR’larla çakışıyor mu? Aynı dosyada paralel authority değişikliği var mı?
- Görev test-first istiyorsa önce düşen test gerçekten çalıştırıldı mı? Çalıştırılamadıysa PASS/red-first iddiası yapılmadı mı?
- Gerekli `modules.validation`, Windows CI ve kapsam uygunsa PC watcher/acceptance sonucu exact head SHA ile eşleşiyor mu?
- PR merge olunca program sırası/kararı değişecek mi; ledger güncellemesi gerekiyor mu?
- PR çıktısında actual `head_sha`, GitHub synthetic merge SHA’dan ayrıldı mı?

### Yeni ajan için 5 satırlık handoff formatı

```text
1. Main: <güncel origin/main SHA> — <son ilgili merge/karar>
2. Aktif şerit: <tek cümle; gerçek authority/cutover durumu>
3. Açık iş: <branch/PR adı veya sıradaki ledger maddesi; canlı PR numarası GitHub’dan doğrulanır>
4. Kanıt: <test/validation/Windows CI/PC acceptance ve exact head SHA; doğrulanmayanı açık yaz>
5. Sonraki adım: <tek somut iş>; yasak/ertelenen kapsam: <kısa sınır>
```

Handoff sohbet hafızasına dayanmaz. Yeni ajan bu beş satırı yalnız başlangıç ipucu olarak kullanır; işe başlamadan önce yine güncel `main`, açık PR listesi ve bu ledger’ı doğrular.

## 8. Bu ledger’ın sınırı

Ledger karar ve sırayı taşır; kanıt üretmez. Bir madde ancak kaynakta merge edilmiş ve ilgili test/validation sonucu exact head SHA ile gösterilmişse “kapanmış” sayılır; belge yazılmış olmak karar verilmiş demek değildir (§4/4). Ledger ile GitHub çelişirse GitHub’ın gösterdiği kaynak durumu, ledger ile bir mimari sözleşme çelişirse sözleşme kazanır ve ledger düzeltilir. Ledger’ı güncel tutmak her adımın kendi PR’sının işidir; bayat ledger, bayat daldan daha tehlikelidir çünkü sonraki ajan ona güvenerek iş seçer.
