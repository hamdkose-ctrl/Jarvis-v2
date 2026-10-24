# GoalState + Core State Reducer v1 — geçiş sınırı

Durum: **Aşama 3a sözleşmesi**. Bu dilim runtime migration değildir.

## Eklenen sözleşme

- `modules/goal_state.py`: JSON-only `goal_state.v1` kanonik snapshot şeması.
- `modules/core_state_reducer.py`: GoalState için tek mantıksal yazıcı olacak saf reducer çekirdeği.
- Her geçerli reducer işlemi yalnız eşleşen `expected_version` ile uygulanır ve sürümü tam `+1` artırır.
- Stale proposal state değiştirmez.
- `done` ve `cancelled` terminaldir; tekrar açılamaz.
- `owner`, `job_id`, `goal` ve `execution_mode` reducer proposal ile yamalanamaz.
- Evidence ve blocker yalnız açık reducer işlemleriyle değişir.
- Audit yalnız `version`, `op`, `state`, `reason_code` tutar; model muhakemesi veya chain-of-thought tutmaz.

## Bu PR'ın özellikle yapmadığı şeyler

- `goal_executor` veya `task_agents` kalıcı kayıtlarını henüz GoalState'e taşımıyor.
- Mevcut `_save` / task journal yazma yollarını sökmüyor.
- Disk persistence için atomik CAS adaptörü eklemiyor.
- WorkerResult fencing, Runtime Event dedup ve crash recovery eklemiyor; bunlar Aşama 4 kapsamıdır.
- Planner, Permission veya Capability Worker davranışını değiştirmiyor.

## Sonraki geçiş

Aşama 3b'de mevcut yürütücüler için compatibility adapter yazılır. Adapter mevcut kayıt biçimini koruyarak Core State Reducer'a proposal üretir; doğrudan büyük-bang migration yapılmaz. Diskte state değiştiren adaptör, kaydedilmiş `version` üzerinde atomik compare-and-swap kanıtı olmadan devreye alınmaz.

Compatibility katmanı artık mevcut olsa da bu, runtime authority cutover anlamına gelmez. Canonical GoalState'in global lifecycle authority olacağı ilk gerçek geçişten önce identity, terminal-state uyuşmazlığı, missing/corrupt state, legacy → canonical projection ve rollback/reconcile sınırları `docs/architecture/GOALSTATE_CUTOVER_V1.md` sözleşmesindeki preflight kapısından geçmelidir. Legacy goal JSON mevcut runtime boyunca write authority olarak kalır; big-bang migration yapılmaz. Yürütme ayrıntıları ileride ayrı ExecutionRecord sınırında tutulur.

Test: `tests/test_core_state_reducer.py`.
