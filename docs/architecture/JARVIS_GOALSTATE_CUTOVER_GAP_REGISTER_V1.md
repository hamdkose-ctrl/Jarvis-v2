# GoalState cutover gap register v1

Durum: **gap register**, bu bir cutover sözleşmesi değildir. `docs/architecture/GOALSTATE_CUTOVER_V1.md` ("CUTOVER_V1") zaten preflight sözleşmesidir ve değiştirilmemiştir; bu doküman onun maddelerinin hangilerinin kaynakta gerçekten kapandığını, hangilerinin hâlâ açık olduğunu ayırır. Kod, test ve CUTOVER_V1 değişmedi; bu PR salt bu dosyayı ekler.

Kaynak doğrulaması commit `9eeba3693f8d830c6ca0cb627803ccb669e37f9` (origin/main) üzerinde yapıldı.

## 1. sync() hatası legacy write'ı engelliyor mu — yeniden doğrulama

`modules/goal_state_save_hook.py`:

```
45  def _atomic(path, data):
46      path = Path(path)
47      job = _legacy_job(path, data)
48      if job is None:
49          return _ORIGINAL_ATOMIC(path, data)
50
51      from modules import goal_state_compat, goal_state_store
52
53      canonical = path.with_name(job['id'] + '.goalstate.json')
54      before = canonical.read_bytes() if canonical.exists() else None
55      synced = goal_state_compat.sync(job, canonical)
56      try:
57          return _ORIGINAL_ATOMIC(path, data)
57      except Exception as legacy_error:
```

Doğrulandı: satır 55 (`goal_state_compat.sync(...)`) `try` bloğunun dışındadır; `try:` satır 56'da başlar. Önceki keşif raporunun iddiası doğru.

`sync()` (`modules/goal_state_compat.py:96-107`) `project()` veya `advance()` çağırır; her ikisi de `_target()`'ı (satır 23-27) kullanır:

```
23  def _target(job: dict) -> str:
24      value = _STATE_MAP.get(job.get('state'))
25      if value is None:
26          raise ValueError('Legacy job state GoalState ile eşlenemiyor.')
27      return value
```

`_STATE_MAP` içinde olmayan bir `job['state']` değeri burada `ValueError` fırlatır. Bu hata `goal_state_save_hook._atomic` içinde satır 55'te, `try` bloğundan önce fırlar. Sonuç:

- Legacy atomic write (satır 57, `_ORIGINAL_ATOMIC(path, data)`) hiç çağrılmaz — legacy journal da yazılmaz.
- `compensate()` çağrılmaz (çünkü `except` bloğuna hiç girilmez) — ama geri alınacak bir canonical yazım da yoktur, çünkü `sync()` kendisi de patlamıştır (CAS/`create()` tamamlanmamıştır).
- `ValueError` çağırana (`release_guard.atomic` üzerinden `goal_executor._save`'e) yayılır; `_record_failure` çağrılmaz, `modules/diagnostics`'e hiçbir iz düşmez.

**Sınıflandırma: BLOCKER değil, ama şu an için `goal_executor`'ın kendi `job['state']` üretimi `_STATE_MAP` kümesiyle kapalı olduğundan (bkz. §6) bir "aktif güvenlik açığı" değil — bugün tetiklenmeyen, gelecekte tetiklenebilir bir fail-closed davranış hatasıdır (yanlış yönde fail-closed: veri kaybına değil, *yazmayı tamamen durdurmaya* yol açar).**

## 2. Güvenlik açığı mı, yoksa observability eksikliği mi?

İkisi de değil tam olarak — ayrım şu şekilde:

- **Veri bütünlüğü açısından güvenli**: Hiçbir yarım/bozuk state kalıcı hale gelmez. Legacy write denenmediği için legacy journal eski haliyle kalır; canonical dosya ya hiç oluşmaz (`create()` CAS'i tamamlanmadıysa) ya da önceki geçerli snapshot'ta kalır (CAS compare_and_swap'a hiç girilmediği için). Drift/corruption riski yoktur.
- **Kullanılabilirlik açısından açık**: Legacy write'ın hiç denenmemesi, kullanıcı tarafında "hedef kaydedilemedi" şeklinde sessiz bir durma anlamına gelir — `job['state']` ileride `_STATE_MAP` dışı bir değer alırsa (bkz. §6), o job için legacy journal bir daha hiç güncellenmez, `goal_executor` tarafı da muhtemelen bir exception görüp kullanıcıya hata döner (render edilmeyen bir hedef).
- **Observability eksikliği**: `_record_failure` yalnız `except Exception as legacy_error` bloğunda çağrılır (satır 59, 65); satır 55'teki hata hiçbir `_record_failure` ya da log çağrısı görmeden yayılır. Bu, hatanın kendisi değil, hatanın **görünürlüğünün** eksik olduğu bir noktadır.

**Sınıflandırma: küçük izole hardening.** Düzeltme kapsamı dar ve izole: `sync()` çağrısını `try` bloğunun içine almak (ve sync hatasında legacy write'ı hâlâ denemek ya da en azından `_record_failure` ile işaretlemek) `goal_state_save_hook.py`'nin kendi içinde kalır, CUTOVER_V1'in kapsadığı identity/terminal/rollback kararlarına dokunmaz. Bu PR bu düzeltmeyi yapmaz (görev kapsamı yalnız gap register).

## 3. created / approval_at / legacy alt-state birleşmeleri / execution_mode

| Alan | Legacy'de nerede tutuluyor | Canonical'da var mı | Sınıflandırma |
|---|---|---|---|
| `created` | `goal_executor.py:697` — job oluşturulurken `'created': time.time()` set edilir; `goal_executor.py:117`'de `job.get('updated') or job.get('created')` okunur (render zaman damgası için) | Yok. `modules/goal_state.py` şemasında (`SCHEMA`, `owner`, `job_id`, `goal`, `execution_mode`, `version`, `state`, `evidence`, `blocker`, `audit` — satır 63) `created` alanı yok; `goal_state_compat.project()` bunu hiç projekte etmiyor. | **migration-preflight kararı** — CUTOVER_V1 §4 "Legacy → canonical projection sınırı" bunu zaten bilinçli kapsam dışı sayıyor (yalnız lifecycle alanları taşınır); audit listesindeki timestamp'lerle kısmen telafi edilebilir ama bugün edilmiyor. Yeni blocker değil, zaten CUTOVER_V1'in kapalı kararı. |
| `approval_at` | `goal_executor.py:297` (`approval` state'ine geçişte set edilir), `goal_executor.py:689` (120 saniyelik onay timeout kontrolü — `time.time()-job['approval_at']>120`), `goal_executor.py:635` görünüm sözlüğünde dönüyor | Yok. Canonical şemada yok, `goal_state_compat.py` projekte etmiyor. | **BLOCKER adayı, ama bugün için CUTOVER_V1'in kapsamı korur.** `approval_at` sadece bir zaman damgası değil, **aktif iş mantığı** taşıyor (120 sn timeout → `approval`'dan `review`'a otomatik düşüş). Bu mantık canonical'da hiç yok; GoalState yalnız `waiting` görür, timeout'u bilmez. CUTOVER_V1 §1 zaten "execution_mode"u karara bağlanmamış sayıyor ama `approval_at`'i ayrıca adlandırmıyor — bu nedenle CUTOVER_V1'e eklenmesi gereken bir **gap**: bir gerçek runtime cutover'da approval-timeout yürütme mantığının nerede (GoalState mi, ExecutionRecord mı) yaşayacağı ayrıca karara bağlanmalı. Bugünkü compatibility-only katmanda zararsız (yalnız legacy tarafı okuyor), o yüzden BLOCKER değil — **migration-preflight kararı** olarak CUTOVER_V1'in "preflight kararları" listesine eklenmesi önerilir. |
| Legacy alt-state birleşmeleri (`approval`/`question`→`waiting`; `review`/`paused`/`interrupted`/`blocked`→`paused`) | `_STATE_MAP` (`goal_state_compat.py:9-20`) | Kısmen. Üst-state korunuyor, alt-state (hangi legacy durumdan geldiği) kayboluyor — geri dönüşte (`advance()`) hangi alt-state'e düşüleceği belirsiz. | **migration-preflight kararı — zaten CUTOVER_V1'de kapalı.** CUTOVER_V1 "Kaynak kodda bugün doğrulanan sınır" bölümünde bu eşleme tablosunu birebir veriyor ve "Projection'ın mevcut state eşleme tablosu ilk cutover için başlangıç kanıtıdır" diyor — yani bu lossy birleşme zaten bilinen ve kabul edilmiş bir preflight durumu, yeni bulgu değil. |
| `execution_mode` | Legacy'de hiç yok (legacy job'da böyle bir alan yok) | Canonical'da var ama `goal_state_compat.project()` (satır 41) sabit `'agent'` kullanıyor — legacy'den türetilmiyor | **migration-preflight kararı — zaten CUTOVER_V1'de kapalı.** CUTOVER_V1 §1 Identity: "`execution_mode` için compatibility katmanındaki sabit `agent` varsayımının cutover sonrası doğru olup olmadığı açıkça karara bağlanmalıdır; bu PR yeni eşleme varsaymaz." Yani doküman bunu zaten açık bırakılmış bir preflight kararı olarak adlandırıyor — gap register'ın yeniden açması gereken bir şey yok, sadece onaylanıyor. |

## 4. Yeni state eklenirse _STATE_MAP unutulması

Senaryo: `goal_executor.py` ileride `job['state']` için yeni bir değer üretmeye başlar (örn. yeni bir ara durum) ama `modules/goal_state_compat.py:_STATE_MAP` güncellenmez.

Sonuç zinciri (kaynaktan doğrulandı):

1. `goal_executor._save` → `release_guard.atomic` (hook ile `goal_state_save_hook._atomic`) çağrılır.
2. `_legacy_job()` yeni state'i de içeren job'u normal şekilde tanır (state değeri `_REQUIRED` alan kontrolünde kullanılmaz, sadece varlık kontrolü yapılır — bkz. `goal_state_save_hook.py:18,31`).
3. `goal_state_compat.sync(job, canonical)` çağrılır (satır 55, `try` dışında).
4. `sync()` → `project()` veya `advance()` → `_target()` → `_STATE_MAP.get(job.get('state'))` → `None` → `ValueError('Legacy job state GoalState ile eşlenemiyor.')`.
5. Hata `try` bloğuna hiç girmeden yayılır → **legacy write de hiç denenmez** → o job için legacy journal yeni state'i hiç kaydedemez.
6. `architecture_guard._CAS_ALLOWLIST` bu senaryoyu etkilemez (CAS'e hiç ulaşılmıyor); bu tamamen `goal_state_compat._target()` seviyesinde fail-closed bir durma.

**Sınıflandırma: migration-preflight kararı + küçük izole hardening (iki ayrı madde).**
- **migration-preflight kararı**: CUTOVER_V1 §4 zaten "yeni state eşlemesi kod ve test kanıtı olmadan dokümana eklenmez" diyerek bunu süreç kuralı olarak kapatmış — yani "yeni state eklenirse `_STATE_MAP` da güncellenmeli" zaten yazılı bir kural. Bu açıdan CUTOVER_V1 bu riski zaten tanımış ve sözleşmeye bağlamış.
- **küçük izole hardening (ayrı, CUTOVER_V1'in kapsamadığı)**: CUTOVER_V1 kuralın "nasıl ihlal edilirse ne olur"ını tanımlamıyor — bugünkü davranış (yeni state eklenip `_STATE_MAP` güncellenmezse **legacy write de tamamen durur**, sadece canonical değil) CUTOVER_V1'de yazılı değil ve muhtemelen istenen davranış değildir (legacy journal'ın canonical sync hatasından etkilenmemesi beklenirdi — CUTOVER_V1 "legacy journal write authority olarak kalır" diyor, ama bu kod yolunda legacy write canonical sync'in başarısına bağımlı hale geliyor). Bu nokta §1/§2'deki bulgu ile aynı kök neden, ayrı maddelendirildi çünkü tetikleyici senaryo farklı (bilinen state'te runtime hata değil, yeni state ekleme sürecinde unutma).

## 5. Sınıflandırma özeti

| Kategori | Sayı | Maddeler |
|---|---|---|
| BLOCKER | 0 | — |
| migration-preflight kararı | 4 | execution_mode sabit `agent` varsayımı (CUTOVER_V1 §1'de zaten açık); legacy alt-state birleşmesi (CUTOVER_V1'de zaten kapalı/kabul edilmiş); `created` alanının projekte edilmemesi (CUTOVER_V1 §4 kapsamında zaten kapalı); yeni state eklenirse `_STATE_MAP` güncelleme zorunluluğu (CUTOVER_V1 §4'te zaten yazılı kural) |
| küçük izole hardening | 2 | `goal_state_save_hook._atomic` satır 55'teki `sync()` çağrısının `try` dışında olması (observability + legacy-write'ın canonical sync hatasına bağımlı hale gelmesi); `approval_at` runtime iş mantığının (120 sn timeout) CUTOVER_V1'in preflight karar listesine ayrıca adıyla eklenmesi gerekliliği |
| deferred | 0 | — |

Not: Hiçbir madde BLOCKER değil çünkü bugünkü kod yolunda hem (a) tüm mevcut legacy state'ler `_STATE_MAP` içinde kapalı, hem de (b) olası hatalar veri bozulmasına değil yalnız yazmanın durmasına yol açıyor (fail-closed, fail-silent değil). Riskler gerçek bir runtime cutover'dan önce, yeni state eklenmeden önce ele alınmalı — ama bugünün compatibility-only katmanını bloke eden bir şey yok.

## 6. Kapsam dışı (bu doküman)

Bu register hiçbir kodu, testi veya `docs/architecture/GOALSTATE_CUTOVER_V1.md`'yi değiştirmez. Önerilen hardening'ler (§2, §4) ayrı, dar bir PR'da ele alınmalıdır; bu PR o değişikliği yapmaz.
