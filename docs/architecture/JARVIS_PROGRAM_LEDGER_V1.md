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
- GitHub PR durumu canlı otoritedir; bu belge anlık PR numaralarını kalıcı gerçek gibi tutmaz.
- Bu ledger karar ve yol haritası otoritesidir. Canlı uygulama durumu için GitHub; mimari karar/sıra için bu ledger + referans verilen sözleşmeler okunur.
- Bir PR bu ledger’daki karar/sırayı değiştiriyorsa merge sonrası ledger güncellemesi ayrıca değerlendirilir.
- Eski veya superseded sohbet/PR notu, güncel kaynak ve GitHub durumunun önüne geçmez.

## 2. Kilitli mimari

Aşağıdaki sınırlar program boyunca değişmez kabul edilir; aksi ancak ayrı mimari RFC ile ele alınır:

- **Core tek authority’dir.** Planner/model/worker/watcher/UI/external agent yalnız proposal/result/event üretir; global lifecycle ve completion kararı Core’dadır. Kaynak: `docs/architecture/JARVIS_STAGE_0_4_GUARD.md`, `docs/architecture/JARVIS_EXECUTION_ARCHITECTURE_V1.md`.
- **Worker yalnız WorkerResult/evidence döndürür.** Worker `succeeded` dese bile global `done` değildir. Fence alanları kabul edilmeden sonuç state’e işlenmez. Kaynak: `modules/worker_result.py`, `modules/worker_result_commit.py`.
- **GoalState yalnız Reducer/CAS üzerinden ilerler.** Worker/model/UI/watcher doğrudan canonical state yazamaz. Stale version, identity ve audit-prefix korunur. Kaynak: `modules/core_state_reducer.py`, `modules/goal_state_store.py`, `docs/architecture/JARVIS_STAGE_0_4_GUARD.md`.
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
| Architecture Guard | Canonical writer, DecisionContext ve direct-executor kaçaklarını statik BLOCKER olarak yakalayan guard mevcut; validation’a bağlı. | `modules/architecture_guard.py`, `docs/architecture/JARVIS_STAGE_0_4_GUARD.md`; architecture-guard PR türü |
| Persisted GoalState corruption hardening | Bozuk UTF-8/JSON/şema snapshot’ı kararlı corruption sınırında fail-closed; CAS/compensation bozuk snapshot üzerine sessizce yazmaz. | `modules/goal_state_store.py`, `tests/test_goal_state_persistence.py`; persistence-hardening PR türü |
| Dual-write parity testleri | Legacy→canonical state/blocker/terminal/idempotency/rollback parity’si persistence testleriyle karakterize edilmiş; bu gerçek cutover değildir. | `modules/goal_state_compat.py`, `modules/goal_state_save_hook.py`, `tests/test_goal_state_persistence.py`; compatibility/parity PR türü |

## 4. Mevcut aktif şerit

**Aktif şerit: GoalState canonical cutover hazırlığı. Gerçek cutover henüz yapılmadı.**

Kaynak: `docs/architecture/GOALSTATE_CUTOVER_V1.md` ve `docs/architecture/GOALSTATE_CUTOVER_GAP_REGISTER_V1.md`. Bugünkü runtime’da legacy `goal_executor` JSON journal write authority olarak kalır; canonical GoalState compatibility projection/sync katmanıdır.

Cutover’a geçmeden önce sıra:

1. **Sync observability hardening:** canonical sync failure tanı noktası görünür olmalı; hata yutulmamalı, legacy write/compensation yanlışlıkla başlamamalı.
2. **Read-only preflight checker:** legacy/canonical çiftleri değiştirmeden identity/missing/corrupt/divergence sınıflarını raporlamalı.
3. **Authority RFC:** canonical authority’nin hangi atomik sınırda devralacağı, missing-state/identity/terminal divergence ve rollback/reconcile politikası açıkça kabul edilmeli.
4. **Yalnız kabul edilmiş migration planı** üzerinden uygulama PR’ları açılmalı.

Bu aşamada “canonical dosya var” veya “compat sync çalışıyor” demek cutover tamamlandı anlamına gelmez.

## 5. Sıradaki iş sırası

Program sırası şudur:

1. Küçük GoalState hardening işleri.
2. Salt-okunur preflight checker ve testleri.
3. Authority RFC / cutover karar sözleşmesi.
4. Kabul edilmiş migration karar/uygulama PR’ları.
5. Final Stage 0–4 acceptance: Architecture Guard BLOCKER=0, full `modules.validation`, current merged main SHA üzerinde gerekli Windows/PC acceptance ve temsilî durable E2E kanıtı.
6. **Ancak bundan sonra** read-only worker/Hermes pilotları ve capability-adoption deneyleri.

Bu sıra, aktif PR’ların merge sırası değildir; canlı mergeability/CI için GitHub kontrol edilir. Bir adım kaynakta zaten merge edilmişse yeniden yapılmaz, sonraki açık adıma geçilir.

## 6. Bilinçli ertelenenler

| Deferred konu | Neden şimdi değil? | Ne zaman yeniden açılır? |
|---|---|---|
| RuntimeEvent durable subscription/producer | Schema/freshness/dedup/commit sınırı var; production subscription producer ayrı borç ve cutover blocker’ı değil. | GoalState authority cutover kararı kapandıktan ve subscription’ın gerçek sahibi/lifecycle’ı ayrı RFC ile tanımlandıktan sonra. |
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
