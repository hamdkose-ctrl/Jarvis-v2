# GoalState cutover runner v1

Durum: **operator onaylı cutover runner**. `modules/goalstate_cutover_runner.py`, `docs/architecture/GOALSTATE_CANONICAL_AUTHORITY_RFC_V1.md` içindeki kabul edilmiş kararları kod içinde guard olarak uygular. Runner `goal_executor`, save-hook veya compatibility `sync()` akışına **bağlı değildir**; yalnız operatör elle çalıştırır. Legacy JSON yazımını durdurmaz (o iş ayrı PR'dır).

## İki adım

1. **`plan(owner_dir)` — salt-okunur.** `goalstate_cutover_preflight.scan()` raporunu alır, her satıra guard eylemi, karar ve authority bilgisi ekler, legacy + canonical dosya byte hash'lerinden bir **plan parmak izi** üretir. Hiçbir dosya yazmaz.
2. **`apply(owner_dir, approved_fingerprint=..., approved_job_ids=[...])` — operatör onaylı.** Yalnız onaylanan `MISSING_CANONICAL` job'lar için tek seferlik backfill yapar.

Komut satırı:

```text
python -m modules.goalstate_cutover_runner <owner_dir>                                  # plan
python -m modules.goalstate_cutover_runner <owner_dir> --approve <parmak_izi> --job <id>  # uygula
```

## Guard tablosu (her preflight reason_code için tek kural)

| reason_code | Eylem | Karar | RFC |
|---|---|---|---|
| `OK` | `NONE` | `ALIGNED` | — |
| `MISSING_CANONICAL` | `OPERATOR_BACKFILL` | `BACKFILL_PENDING_OPERATOR` | Karar 3a (B) |
| `STATE_DIVERGENCE` | `REPORT_ONLY` | `AUTHORITY_SIDE_WINS` (`winner` = kaydın authority'si) | Karar 4b (A) |
| `TERMINAL_DIVERGENCE`, canonical terminal | `REPORT_ONLY` | `CANONICAL_TERMINAL_WINS` (`winner='canonical'`) | Karar 4a (A) |
| `TERMINAL_DIVERGENCE`, legacy terminal | `REPORT_ONLY` | `AUTHORITY_SIDE_WINS` | Karar 4b (A) |
| `IDENTITY_MISMATCH` | `BLOCKED` | `HUMAN_REVIEW_REQUIRED` | Karar 3c (A) |
| `CANONICAL_CORRUPT` | `BLOCKED` | `HUMAN_REVIEW_REQUIRED` | Karar 3d (A) |
| `UNKNOWN_LEGACY_STATE` | `BLOCKED` | `HUMAN_REVIEW_REQUIRED` | Karar 3e (A) |
| `INVALID_LEGACY_RECORD` | `BLOCKED` | `HUMAN_REVIEW_REQUIRED` | Karar 3 genel ilke |

Bilinmeyen bir reason_code `BLOCKED` sayılır. Mutasyon yapan tek eylem `OPERATOR_BACKFILL`'dir; divergence satırları raporlanır, runner CAS/reconcile yapmaz (canonical takip, mevcut save-hook `sync()` yolunda kalır).

## Fail-closed sınırı

`apply()` sırası; ilk hata işlemi durdurur:

1. Onay yoksa (boş parmak izi, boş veya tekrarlı job listesi) → `OPERATOR_APPROVAL_REQUIRED`, dosya değişmez.
2. Taze plan yeniden hesaplanır. Owner dizininde **tek bir** `BLOCKED` satır bile varsa → `CUTOVER_BLOCKED`, hiçbir job backfill edilmez.
3. Taze parmak izi onaylananla aynı değilse → `PLAN_DRIFT` (disk onaydan sonra değişti; yeniden plan + onay gerekir).
4. Onaylanan her job taze planda `MISSING_CANONICAL` olmalı; değilse → `OPERATOR_APPROVAL_REQUIRED`.
5. Her job için: legacy kayıt yeniden okunur → `goal_state_compat.operator_backfill_missing_canonical_once(..., operator_approved=True)` (kanonik dosya varsa `create()` reddeder) → doğrulama: diskteki kayıt dönen kayıtla aynı, authority `legacy`, preflight satırı `OK`. Doğrulama tutmazsa `CUTOVER_VERIFICATION_FAILED` / `AUTHORITY_FLIP_REFUSED` ile durulur.

Kör retry, otomatik silme veya repair yoktur (RFC ilke 5). Yarıda kesilen çalışmada tamamlanan backfill'ler geçerli ve doğrulanmış kayıt olarak kalır; yeniden çalıştırmada onlar `OK` görünür, kalanlar için yeni plan ve yeni onay gerekir (idempotent).

## Authority flip noktası (Karar 2)

`AUTHORITY_FLIP_POINT = 'JOB_CREATION'`. Authority yalnız job yaratılırken (`goal_state_compat.project`, `authority='canonical'`) belirlenir. Runner var olan hiçbir kaydın authority'sini değiştirmez. Canonical kaydı olmayan legacy job canonical sync'ten önceki, yani flip noktasından önceki in-flight bir job'dur; bu yüzden backfill kaydı **`authority='legacy'`** ile yaratılır. Bu PR ile `operator_backfill_missing_canonical_once` aynı kuralı uygular (önceden `project()` üzerinden `canonical` işaretliyordu, bu da gizli bir runtime authority flip demekti). `project()` ve `sync()` davranışı değişmedi.

## Mimari sınır

- Runner `goal_state_store.create/compare_and_swap/compensate` çağırmaz; tek yazma yolu `goal_state_compat` içindeki operatör API'sidir (ARCH-001/004/005 allowlist'leri değişmedi).
- Rapor, preflight ile aynı gizlilik sınırını taşır: owner adı/yolu, `request`, blocker veya ham dosya içeriği yazılmaz.

## Testler

`tests/test_goalstate_cutover_runner.py`: guard tablosunun tamlığı, plan salt-okunurluğu, onaysız/yanlış onaylı/bayat planlı apply'ın byte düzeyinde hiçbir şeyi değiştirmemesi, her blocker türünün owner'ı tamamen durdurması, backfill'in `legacy` authority ile yaratılıp sonraki `sync()`'te öyle kalması, yarıda kesilme ve doğrulama hatasında silme/retry olmaması, divergence kararları, runner'ın sync/save-hook'a bağlı olmaması ve Architecture Guard BLOCKER=0.
