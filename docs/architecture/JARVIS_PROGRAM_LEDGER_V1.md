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
- **GoalState yalnız Reducer/CAS üzerinden ilerler.** Worker/model/UI/watcher doğrudan canonical state yazamaz. Stale version, identity ve audit-prefix korunur. Canonical storage mutation API’lerinin her biri ayrı dosya allowlist’ine bağlıdır ve allowlist’ler birbirine izin vermez: `create` yalnız `goal_state_compat`, `compare_and_swap` yalnız onaylı commit adaptörleri (`goal_state_compat`, `worker_result_commit`, `runtime_event_commit`), `compensate` yalnız onaylı rollback/promotion yolları. Kaynak: `modules/core_state_reducer.py`, `modules/goal_state_store.py`, `modules/architecture_guard.py` (ARCH-001/004/005), `docs/architecture/JARVIS_STAGE_0_4_GUARD.md`.
- **Canonical sync başarısızsa işlem orada durur.** `goal_state_compat.sync()` hatası yutulmaz; legacy write ve compensation başlamaz, hiçbir dosyada otomatik repair yapılmaz. Canonical-authority işlerde başarılı sync/ExecutionRecord sonrasında legacy lifecycle JSON yazımı yapılmaz (#385); legacy-authority kayıtlar geçiş süresince uyumluluk yazımını sürdürebilir. Hata kendi tanı noktasıyla (`_atomic:canonical_sync`) ayrıştırılır. Kaynak: `modules/goal_state_save_hook.py`, `docs/architecture/GOALSTATE_CUTOVER_GAP_REGISTER_V1.md`.
- **Karar sırası:** Domain invariant → Decision Authority → JIT Permission → Effect Policy → Worker. Permission/effect kararları worker’dan önce ve gerektiğinde yan etkiden hemen önce tekrar doğrulanır. `worker_result_hook.execute(...)` yalnız durable specialist orchestrator sınırından çağrılabilir; bu wrapper ikinci execution authority değildir. Kaynak: `modules/runtime_execution_gate.py`, `modules/permission_gate.py`, `modules/architecture_guard.py` (ARCH-002/003/007), capability manifest sözleşmeleri.
- **Effect/crash recovery:** journal-required effect dış çağrıdan önce durable intent ister; intent var/receipt yoksa `unknown`, blind retry yok, yalnız read-only reconcile. Receipt-required effect `done` dönse bile doğrulanmış receipt yoksa Core success commit’i yapılmaz (#445). Receipt olsa bile global completion değildir. Kaynak: `modules/effect_journal.py`, `modules/crash_recovery.py`, `modules/effect_recovery_runtime.py`, `docs/architecture/JARVIS_EFFECTFUL_WORKER_JOURNAL_MATRIX_V1.md`.
- **UI business authority taşımaz.** UI presentation/interaction katmanıdır; lifecycle/verification/execution kararları canonical Core servislerindedir. Ödenmiş `team_control` / `team_verify` borcu yeniden eklenirse ARCH-006 blocker olur; güncel UI authority baseline boştur. Kaynak: `docs/architecture/JARVIS_UI_CORE_BOUNDARY.md`, `modules/architecture_guard.py`.
- **Memory/session/cron GoalState değildir.** Memory davranış/context girdisidir, session konuşma metadata’sıdır, cron yalnız zamanlama ifadesidir; bunlar kendi başına lifecycle/completion/permission authority yaratamaz. F-003 için 0–4’te ikinci capability sistemi kurulmaz; ayrıntılı lifecycle/context işleri Faz 11’dedir. Kaynak: `docs/Jarvis_Yol_Haritasi_0_4_Drive_Fikir_Ekleri.md`.
- **Hermes/external agent ikinci Core değildir.** Yalnız adapter/worker adayıdır; kendi planner/engine/permission/state otoritesini Jarvis Core’un yerine koyamaz. Kaynak: `docs/architecture/JARVIS_HERMES_ADAPTER_BOUNDARY_V1.md`, `docs/architecture/JARVIS_EXTERNAL_SKILL_ADOPTION_V1.md`.

## 3. Tamamlanan temel

Bu bölüm “program temeli mevcut” anlamına gelir; her madde ayrı acceptance/ürün kapsamı iddiası değildir.

| Temel | Kaynak-doğrulanmış durum | Referans |
|---|---|---|
| Aşama 0–4 ana omurga | Tek execution spine, manifest, decision/permission/effect sırası, GoalState Reducer/CAS, WorkerResult fence ve crash-recovery sınırları kaynakta tanımlı ve Architecture Guard ile korunuyor. | `docs/architecture/JARVIS_STAGE_0_4_GUARD.md`, `modules/architecture_guard.py`; mimari/guard PR türü |
| JarvisBench v0 + fixture schema | Deterministik read-only evaluator, v0 case kataloğu ve observation fixture şeması mevcut; canlı acceptance yerine geçmez. | `modules/jarvis_bench.py`, `docs/architecture/JARVIS_BENCH_V0.md`, `tests/test_jarvis_bench.py`; benchmark/fixture PR türü |
| Provider structured failures | Provider/runtime hataları için stabil `reason_code` ve `recovery_class` üretimi goal failure sonucuna bağlanmış; raw provider secret kullanıcı metnine taşınmamalı. | `modules/failure_policy.py`, `modules/goal_executor.py`, `tests/test_goal_failure_policy.py`; provider-resilience PR türü |
| Effect journal manifest coverage | `conditional + required` capability’lerde intent/receipt/reconcile kuralı tanımlı; receipt’siz `done` success commit değildir, blind retry yasak. | `modules/capability_manifest.py`, `modules/effect_recovery_runtime.py`, `modules/specialist_orchestrator.py`, `docs/architecture/JARVIS_EFFECTFUL_WORKER_JOURNAL_MATRIX_V1.md`; #445 |
| Architecture Guard | Statik BLOCKER kuralları ARCH-000..ARCH-007 içinde canonical writer, DecisionContext, direct executor/wrapper ve UI authority sınırlarını korur. Alias (`import X as Y`, `from X import Z as W`) çağrılarını AST üzerinden çözer; dinamik `getattr`/`eval`/import hook kapsam dışı. `modules.validation` guard’ı zorunlu çalıştırır. | `modules/architecture_guard.py`, `tests/test_architecture_guard.py`, `docs/architecture/JARVIS_STAGE_0_4_GUARD.md`; #435/#447 |
| Persisted GoalState corruption hardening | Bozuk UTF-8/JSON/şema snapshot’ı kararlı corruption sınırında fail-closed; CAS/compensation bozuk snapshot üzerine sessizce yazmaz. | `modules/goal_state_store.py`, `tests/test_goal_state_persistence.py`; persistence-hardening PR türü |
| Legacy/canonical parity ve compatibility | Legacy-authority kayıtların geçiş davranışı persistence testleriyle karakterize edilmiştir; canonical-authority yeni işlerde legacy lifecycle yazımı #385 ile durmuştur. Eski JSON dosyasının diskte bulunması tek başına write authority olduğu anlamına gelmez. | `modules/goal_state_compat.py`, `modules/goal_state_save_hook.py`, `tests/test_goal_state_persistence.py`; #347/#385 |
| Canonical sync failure observability | Save-hook, `sync()` hatasında ayrı tanı noktası üretiyor, aynı exception’ı yeniden fırlatıyor; legacy write/compensation çağrılmıyor, canonical byte değişmiyor. PR #305. | `modules/goal_state_save_hook.py`, `tests/test_goal_state_persistence.py`; observability PR türü |
| Salt-okunur cutover preflight checker | Owner dizinini olduğu gibi okur, değiştirmeden tarar; `OK`, `INVALID_LEGACY_RECORD`, `UNKNOWN_LEGACY_STATE`, `MISSING_CANONICAL`, `CANONICAL_CORRUPT`, `IDENTITY_MISMATCH`, `STATE_DIVERGENCE`, `TERMINAL_DIVERGENCE` reason kodlarını döndürür. Dosya yazmaz, CAS/create/compensate çağırmaz, repair yapmaz. PR #306. Bu aracın `OK` üretmesi gerçek makinedeki bütün kayıtların promotion edildiği anlamına gelmez. | `modules/goalstate_cutover_preflight.py`, `tests/test_goalstate_cutover_preflight.py`, `docs/architecture/GOALSTATE_CUTOVER_PREFLIGHT_V1.md`; preflight-tool PR türü |
| Canonical authority RFC | Dört cutover blocker’ı için kararlar kabul edilmiş ve uygulama hattı merge edilmiştir: yeni işte canonical authority, legacy-authority kayıt için kontrollü migration/promotion, terminal uyumluluğu ve rollback sınırları. | `docs/architecture/GOALSTATE_CANONICAL_AUTHORITY_RFC_V1.md`; #347/#349/#385/#422 |
| Operator onaylı cutover runner | RFC kararlarını guard tablosu olarak uygular: salt-okunur `plan()` + parmak izi, yalnız onaylı job’larda kontrollü backfill/promotion, owner genelinde fail-closed blocker, plan drift ve yazım sonrası doğrulama. Runner’ın yalnız operatör tarafından elle çalıştırılması tasarlanmış sözleşmedir; runtime’a otomatik bağlanmaması eksik wiring değildir. | `modules/goalstate_cutover_runner.py`, `tests/test_goalstate_cutover_runner.py`, `docs/architecture/GOALSTATE_CUTOVER_RUNNER_V1.md`; #348/#422 |
| UI/Core authority borcu | `team_control` ve `team_verify` kararları canonical Core servislere taşındı; eski UI authority dependency baseline kaldırıldı. | `modules/team_control_service.py`, `modules/team_verify_service.py`, `modules/architecture_guard.py`; #441/#444 |
| Faz 0 final kapanış kanıtı | Gerçek PC legacy taraması ve 18/18 promotion sonrası aday kalmadı; exact `main@2da471412a53...` üzerinde Architecture Guard, full validation, Windows CI ve gerçek-PC watcher acceptance PASS. | `docs/architecture/JARVIS_PHASE0_CLOSEOUT_2026-10-29.md` |

## 4. Mevcut aktif şerit

**Faz 0 ✅ kapanmıştır. Aktif program sırası artık Faz 1’in canlı GitHub durumuyla doğrulanmış gerçek açık işlerine geçer; stale Faz 0 maddeleri yeniden açılmaz.**

Faz 0 kapanış kanıtı: `docs/architecture/JARVIS_PHASE0_CLOSEOUT_2026-10-29.md`.

Kapanışta doğrulananlar:

1. **Sync observability / corruption / canonical writer guard — kapalı.** Canonical storage mutation sınırları statik guard ve persistence testleriyle korunuyor.
2. **Cutover preflight + operator runner — kapalı.** Runner’ın manuel olması bilinçli güvenlik sözleşmesidir; otomatik runtime wiring yapılmaz.
3. **Canonical-authority legacy lifecycle write stop — kapalı.** #385 sonrası canonical-authority işlerde eski `<id>.json` lifecycle yazımı yapılmaz.
4. **Legacy authority gerçek-PC cutover — kapalı.** Gerçek PC’de bulunan 18 uyumlu legacy-authority adayın 18’i mevcut #422 hattıyla canonical’a promote edildi; son planda blocker, backfill veya promotion adayı kalmadı.
5. **UI/Core authority borcu — kapalı.** `team_control` #441 ve `team_verify` #444 ile Core servislere taşındı; ARCH-006 geri dönüşü engeller.
6. **Effect receipt / Decision Authority wrapper kaçışı — kapalı.** #445 receipt-required effect’i receipt’siz success commit’ten fail-closed’a taşıdı; #447 wrapper üzerinden gate bypass’ını ARCH-007 blocker yaptı.
7. **F-003 — yeni Faz 0 capability işi değildir.** Memory ≠ Task State ≠ Context ayrımı 0–4 invariantıdır; ayrıntılı context/memory lifecycle Faz 11’dedir.
8. **Final exact-main acceptance — kapalı.** `main@2da471412a53d275659d2f82ac91f2558478c0e9` üzerinde Architecture Guard PASS, full validation `3391 test / 3 skip` PASS, Windows CI #910 SUCCESS ve gerçek-PC watcher `STATUS=passed` exact-SHA arşivi mevcut.

#347 compatibility bridge Faz 0 kapanışını bloklamaz. Gerçek-PC legacy-authority adayı kalmadığı için köprü daha sonra ayrı ve kanıtlı cleanup olarak değerlendirilebilir; cleanup yapılmadan da Faz 0 kapalıdır.

## 5. Sıradaki iş sırası

Program sırası şudur:

1. **Faz 0’ı yeniden açma.** `docs/architecture/JARVIS_PHASE0_CLOSEOUT_2026-10-29.md` final kanıt kaydıdır; yeni somut regresyon veya ayrı RFC yoksa eski Faz 0 backlog satırları tekrar iş seçimi değildir.
2. **Faz 1 canlı durumunu yeniden denetle.** GitHub’daki açık/merge edilmiş PR’ları ve güncel `main` kodunu roadmap satırlarıyla karşılaştır; stale F-009/#428 veya benzeri satırları yeniden kodlama işi sanma.
3. **Gerçek açık Faz 1 işini tek PR olarak ele al.** Aynı iş daha önce merge edilmişse tekrar açma; açık PR varsa onu doğrula/bitir.
4. **Her Faz 1 adımında** exact-head validation + Windows CI + kapsam uygunsa gerçek-PC acceptance kuralını sürdür.

Bu sıra, aktif PR’ların merge sırası değildir; canlı mergeability/CI için GitHub kontrol edilir. Bir adım kaynakta zaten merge edilmişse yeniden yapılmaz, sonraki açık adıma geçilir.

## 6. Bilinçli ertelenenler

| Deferred konu | Neden şimdi değil? | Ne zaman yeniden açılır? |
|---|---|---|
| ~~RuntimeEvent durable subscription/producer~~ | Kapandı (26 Ekim 2026, Faz 2-2): `modules/runtime_subscription.py` kalıcı abonelik + `source_watch`/webhook üreticisi (#374), hedef sahipliği `bind_job` ile; ARCH-W001 temiz. Ayrıntı: `docs/roadmap-runtime-event-subscription-notu.md`. | Yeni olay kaynağı (webhook/queue) eklenince aynı abonelik modeline bağlanır. |
| ExecutionRecord ayrıntıları | Step/output/waiting/retry gibi yürütme ayrıntıları GoalState global lifecycle’a doldurulmamalı. | ExecutionRecord için gerçekten yeni provenance/retention ihtiyacı doğarsa ayrı RFC/PR olarak. |
| `created` / `approval_at` canonical taşıma kararı | `created` provenance; `approval_at` yaklaşık 120 sn approval timeout/control bağlamı taşır. Bunları GoalState’e zorla eklemek doğru kabul edilmedi. | Approval timeout’un kalıcı sahibi değişirse veya mevcut sözleşme yetersiz kalırsa. |
| Gerçek worker/product capability genişlemesi | Core güvenlik ve Faz 0 kapanış kanıtı tamamlanmadan yeni capability’ler ikinci motor/otorite riski yaratabilirdi. | Faz 0 final acceptance tamamlandı; bundan sonra yalnız roadmap sırası ve read-only benchmark → adapter → manifest → evidence/receipt kabul hattı içinde açılır. |

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

Ledger karar ve sırayı taşır; kanıt üretmez. Bir madde ancak kaynakta merge edilmiş ve ilgili test/validation sonucu exact head SHA ile gösterilmişse “kapanmış” sayılır; belge yazılmış olmak karar verilmiş demek değildir. Ledger ile GitHub çelişirse GitHub’ın gösterdiği kaynak durumu, ledger ile bir mimari sözleşme çelişirse sözleşme kazanır ve ledger düzeltilir. Ledger’ı güncel tutmak her adımın kendi PR’sının işidir; bayat ledger, bayat daldan daha tehlikelidir çünkü sonraki ajan ona güvenerek iş seçer.