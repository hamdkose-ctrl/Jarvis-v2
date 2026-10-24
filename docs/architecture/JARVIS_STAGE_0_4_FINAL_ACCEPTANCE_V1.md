# Jarvis Stage 0–4 Final Acceptance Audit v1

**Tür:** Salt-okunur kabul kanıtı denetimi.  
**Denetlenen baseline:** `origin/main = 69383779794c27a02dc1823e274de1aeeeb1caf1` (`docs: add Jarvis program ledger and handoff rules (#308)`).  
**Karar sınırı:** Bu belge Stage 0–4'ü "kabul edildi/tamamlandı" ilan etmez. Yalnız `JARVIS_PROGRAM_LEDGER_V1.md` §5'teki beş kabul şartının mevcut kanıt durumunu kaydeder.

İzin verilen durumlar yalnız şunlardır:

- **KANITLANMIŞ** — kaynak veya gerçek komut/CI/PC çıktısıyla gösterildi.
- **EKSİK** — kabul şartını karşılayan kanıt mevcut değil; eksik parça açıkça gösterildi.
- **DOĞRULANAMAZ_BU_ORTAMDA** — bu cloud oturumunun yürütme/checkout sınırı nedeniyle komut gerçekten çalıştırılamadı; PASS/FAIL iddiası yapılmaz.

## Özet

| # | Ledger kabul şartı | Durum | Kısa gerekçe |
|---|---|---|---|
| 1 | Architecture Guard `BLOCKER=0` | **DOĞRULANAMAZ_BU_ORTAMDA** | Exact self-scan komutu denendi; bu oturumda repo checkout'u olmadığı için `modules` import edilemedi. |
| 2 | Tam `python -X utf8 -m modules.validation` | **DOĞRULANAMAZ_BU_ORTAMDA** | Exact komut denendi; repo checkout'u olmadığı için `modules.validation` yüklenemedi. Bu bir test FAIL değil, yürütme ortamı engelidir. |
| 3 | Current merged main SHA üzerinde Windows CI | **EKSİK** | #304–#308 PR head'lerinde `testler-windows` SUCCESS var; fakat current merged main `6938377…` üzerinde `testler-windows` check-run yok. |
| 4 | Current merged main SHA üzerinde gerçek PC watcher/acceptance | **EKSİK** | #304/#305/#306/#308 PR head'lerinde watcher PASS var, #307'de acceptance yorumu yok; current merged main `6938377…` için exact-SHA acceptance kaydı yok. |
| 5 | Temsilî durable E2E / effect-journal manifest coverage | **KANITLANMIŞ** | `tests/test_effect_crash_restart_e2e.py` ve `tests/test_crash_recovery.py` güncel main'de mevcut ve manifest-driven journal, intent-before-effect, no-blind-retry, reconcile/fence/CAS ve worker-done ≠ global-completion sınırlarını doğrudan kilitliyor. |

Bu tablo **final acceptance kararı değildir**. Özellikle 3 ve 4 kapanmadan ledger §5'teki "current merged main SHA üzerinde gerekli Windows/PC acceptance" şartı karşılanmış sayılmaz.

## 1. Architecture Guard `BLOCKER=0`

**Durum: DOĞRULANAMAZ_BU_ORTAMDA**

İstenen exact komut bu cloud oturumunda gerçekten denendi:

```text
python -X utf8 -m modules.architecture_guard
```

Gerçek çıktı:

```text
/opt/pyvenv/bin/python: Error while finding module specification for
'modules.architecture_guard' (ModuleNotFoundError: No module named 'modules')
exit code: 1
```

Bu çıktı "Architecture Guard FAIL" veya "BLOCKER var" anlamına gelmez. Çalışma dizininde private repo checkout'u bulunmadığı için self-scan hiç başlamamıştır; dolayısıyla blocker sayısı bu ortamda ölçülememiştir.

Kaynak tarafında guard mevcut ve `docs/architecture/JARVIS_STAGE_0_4_GUARD.md` ile `modules/architecture_guard.py` canonical writer, DecisionContext ve direct-executor sınırlarını BLOCKER olarak tanımlar. #304 (`gpt/goalstate-storage-writer-guard`, head `642739c1e845c5226d75984e0739f8162b3d8144`) Windows `testler-windows` check-run'ı SUCCESS olmuştur; fakat bu, istenen **current main self-scan çıktısının** yerine geçirilmez.

**Nerede doğrulanabilir?** Güncel `origin/main` checkout'u olan CI veya geliştirici/Windows çalışma ortamında exact self-scan çalıştırılarak; rapor BLOCKER sayısı ve kural kimlikleriyle kaydedilmelidir.

## 2. Tam `modules.validation` ve bağımsız odak testleri

**Durum: DOĞRULANAMAZ_BU_ORTAMDA**

Exact full-validation komutu denendi:

```text
python -X utf8 -m modules.validation
```

Gerçek sonuç:

```text
ModuleNotFoundError: No module named 'modules'
exit code: 1
```

Dolayısıyla burada dependency/pypi aşamasına dahi gelinmedi. Bu oturum için gerçek engel **private repo checkout'unun yerel çalışma alanında bulunmaması**dır. Bu sonuç bir validation FAIL değildir ve PASS iddiası da yapılmaz.

Ayrıca dependency-light/odak adayları gerçekten denendi:

| Komut | Gerçek sonuç |
|---|---|
| `python -X utf8 -m unittest tests.test_architecture_guard` | `ModuleNotFoundError: No module named 'tests'`; test başlamadı |
| `python -X utf8 -m unittest tests.test_jarvis_bench` | `ModuleNotFoundError: No module named 'tests'`; test başlamadı |
| `python -X utf8 -m unittest tests.test_goal_state_persistence` | `ModuleNotFoundError: No module named 'tests'`; test başlamadı |
| `python -X utf8 -m unittest tests.test_effect_crash_restart_e2e tests.test_crash_recovery` | `ModuleNotFoundError: No module named 'tests'`; testler başlamadı |

Sonuç: bu cloud oturumunda **bağımsız olarak çalıştırılabilen repo testi yoktur**; sebep test bağımlılığı değil, repo checkout/import kökünün olmamasıdır. GitHub üzerindeki geçmiş Windows/PC sonuçları aşağıda ayrı kanıt olarak raporlanır ve bu yerel full-validation şartının yerine geçirilmez.

**Nerede doğrulanabilir?** Güncel current-main checkout'u ve repo bağımlılıkları olan Windows/CI ortamında `python -X utf8 -m modules.validation` çalıştırılarak.

## 3. Windows CI kanıtı

**Durum: EKSİK**

GitHub commit check-run kayıtları PR'ların **actual head SHA** değerleri üzerinden kontrol edildi. #304–#308'in her birinde `testler-windows` tamamlanmış ve `success` olmuştur:

| PR | Actual PR head SHA | Check-run | Sonuç |
|---|---|---|---|
| #304 | `642739c1e845c5226d75984e0739f8162b3d8144` | `testler-windows` | `completed / success` |
| #305 | `18dc5181620f520a945ba1f69958b92f77c93b97` | `testler-windows` | `completed / success` |
| #306 | `5958c0a93efabc0e0b89f3eb4f430572a969629f` | `testler-windows` | `completed / success` |
| #307 | `bdd65bb68a48f6050b74c6b1035819cce0fdf01f` | `testler-windows` | `completed / success` |
| #308 | `e80ae330534f5cd19eb77b7f00cb973cfbffac7f` | `testler-windows` | `completed / success` |

Bunlar ayrı ayrı gerçek ve değerlidir; ancak final acceptance şartı ledger'da **current merged main SHA** için yazılmıştır. Current main:

```text
69383779794c27a02dc1823e274de1aeeeb1caf1
```

Bu SHA'nın `/check-runs` kaydında `testler-windows` yoktur. Tek görülen check-run:

```text
name: bekci
status: completed
conclusion: failure
```

Bu `bekci` failure'ı `testler-windows` sonucu gibi yorumlanmaz; fakat current-main Windows acceptance kanıtı da üretmez. Ayrıca #304–#308 branch'leri aynı anda güncel birleşik main ağacını test etmiş değildir; eski PR-head SUCCESS kayıtları final birleşik baseline'a otomatik devredilemez.

**Eksik iş/kanıt:** `69383779794c27a02dc1823e274de1aeeeb1caf1` veya bu audit PR sonrası oluşacak yeni current-main SHA üzerinde Windows `testler-windows` SUCCESS kanıtı gerekir. Bu belge workflow tetiklemez.

## 4. Gerçek PC watcher / acceptance kanıtı

**Durum: EKSİK**

PR yorumları `<!-- jarvis-pc-acceptance -->` işaretiyle kontrol edildi:

| PR | Watcher'ın yazdığı commit | Genel durum | Validation |
|---|---|---|---|
| #304 | `642739c1e845` | `passed` | `passed` |
| #305 | `18dc5181620f` | `passed` | `passed` |
| #306 | `5958c0a93efa` | `passed` | `passed` |
| #307 | — | **kayıt yok** | — |
| #308 | `e80ae330534f` | `passed` | `passed` |

#306'da ayrıca daha eski head `2f119f76c6d0` için bir PASS yorumu vardır; final branch head için esas alınan yorum `5958c0a93efa` kaydıdır.

Bu kayıtlar gerçek iş PC'sindeki watcher tarafından otomatik yazılmış acceptance kanıtlarıdır; ancak current merged main `69383779794c27a02dc1823e274de1aeeeb1caf1` için exact-SHA watcher/acceptance kaydı bulunmamaktadır. #307 için de PR seviyesinde `jarvis-pc-acceptance` yorumu yoktur.

**Eksik iş/kanıt:** current merged main SHA üzerinde gerçek Windows PC acceptance PASS kaydı gerekir. Bu audit PR watcher veya PC testini tetiklemez.

## 5. Durable E2E / effect journal manifest coverage

**Durum: KANITLANMIŞ**

Güncel main'de `tests/test_effect_crash_restart_e2e.py` ve `tests/test_crash_recovery.py` gerçekten vardır.

`tests/test_crash_recovery.py` şu sözleşmeleri doğrudan test eder:

- intent yok → `not_started / policy_required / EFFECT_INTENT_MISSING`;
- intent var, receipt yok → `unknown / read_only_reconcile / RECEIPT_MISSING_NO_BLIND_RETRY`;
- verified receipt → `succeeded / no_retry`;
- `effect_recovery_runtime.required(kind)` her task capability için manifest `replay == 'conditional'` ve `reconciliation == 'required'` politikasını birebir izler;
- `research`, `account`, `verify` read-only olduğu için journal-required değildir;
- `publish` external-write olduğu için journal-required'dır.

`tests/test_effect_crash_restart_e2e.py` temsilî durable akışta şunları kilitler:

1. journal-required normal execute yolunda `record_intent()` worker/effect çağrısından **önce** çalışır;
2. crash sonrası intent + no receipt durumu read-only reconcile ile giderilir, provider effect kör tekrar edilmez;
3. verified receipt varsa reconcile veya evidence bump tekrar edilmez;
4. foreign/stale WorkerResult fence kabul edilmez;
5. recovered output normal WorkerResult fence → Reducer/CAS hattından evidence'a girer;
6. read-only capability journal hattına hiç girmez;
7. worker çıktısındaki `state='done'` canonical GoalState'i global `done` yapmaz; global completion ayrı Core otoritesinde kalır.

Bu içerik, ledger §3'teki **"effect journal manifest coverage"** iddiasını kaynak düzeyinde karşılar: journal kapsamı sabit bir `publish` özel-kuralına değil manifest `conditional + required` politikasına bağlanmıştır ve crash-recovery/no-blind-retry/fence/CAS sınırları temsilî E2E ile karakterize edilmiştir.

Bu madde için **KANITLANMIŞ** denmesi, bu cloud oturumunda E2E test komutunun yeniden PASS çalıştığı anlamına gelmez. Yeniden yürütme §2'deki checkout engeli nedeniyle doğrulanamamıştır; burada kanıtlanan şey testlerin güncel main'de mevcut olduğu ve içeriklerinin ledger'daki coverage sözleşmesini gerçekten kapsadığıdır.

## Sonuç — karar değil durum tespiti

Bu audit final Stage 0–4 acceptance'ı tamamlanmış ilan etmez.

Mevcut beş şartın dağılımı:

```text
KANITLANMIŞ: 1
EKSİK: 2
DOĞRULANAMAZ_BU_ORTAMDA: 2
```

Final kabul kararı verilebilmesi için en azından:

- current merged main checkout'unda Architecture Guard self-scan sonucu görünür olmalı,
- current merged main üzerinde full `modules.validation` sonucu bulunmalı,
- aynı current-main baseline için Windows `testler-windows` SUCCESS olmalı,
- aynı current-main baseline için gerçek PC watcher/acceptance PASS kanıtı bulunmalı.

Bu belge eksikleri düzeltmez, workflow/watcher tetiklemez ve migration/capability davranışı değiştirmez.
