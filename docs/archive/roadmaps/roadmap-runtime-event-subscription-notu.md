# Yol haritası notu — Durable RuntimeEvent subscription

**Durum:** Kapandı (Faz 2-2, 26 Ekim 2026) — ilk production kaynak `source_watch`  
**Tarih:** 24 Ekim 2026, güncelleme 26 Ekim 2026

## Verilen kararlar (Faz 2-2)

Tek abonelik sistemi: `modules/runtime_subscription.py` (servis veritabanında `runtime_subscriptions` tablosu). Test: `tests/test_runtime_subscription.py`, `tests/test_runtime_subscription_jobs.py`.

- **Sahip:** Kaynak takibini (`monitor add`) çalıştıran hedef, yani `identity['job_id']`; `bind_job` ile bağlanır. Canonical GoalState yoksa veya hedef bitmişse abonelik açılmaz, takip yine eklenir.
- **Sahipsiz kaynak:** Aktif hedef aboneliği olmayan kaynak için `ensure_source` `source-<özet>` adlı ayrı bir GoalState açar (webhook kaynakları da böyle).
- **Kimlik alanları:** `source_event_key` takip kuralının kimliği (webhook için `webhook:<kaynak>`). `fresh_after` abonelik zamanıdır; daha eski olaylar bayat sayılır. `resume_token` rastgele ve kalıcıdır.
- **Akış:** `source_watch.poll` yeni öğeleri `publish` eder → `runtime_event_commit` → Reducer `append_evidence` + CAS. CAS yarışında bir kez yeniden okur. Dedup abonelik başına kalıcı seen dosyasıyla.
- **Yaşam döngüsü:** Hedef `done/cancelled` olursa ilk olayda abonelik kapanır (`TerminalStateError`). Takip kuralı silinince `close_source` o kaynağın bütün aboneliklerini kapatır.
- **Fan-out:** Aynı kurala bağlı her aktif abonelik kendi GoalState'ine ayrı evidence alır.
- **Sınır:** Event hiçbir state/completion kararı vermez; yalnız evidence ekler.

Aşağıdaki bölümler tarihsel tasarım notudur.

## Hazır altyapı, eksik production bağ

`RuntimeEvent.v1`, freshness/dedup, persistent seen ve `runtime_event_commit` ile Reducer + CAS evidence altyapısı hazır ve testlidir. Ancak production tarafında mevcut `source_watch`, webhook veya queue akışını belirli bir durable GoalState job'ına bağlayan subscription kimliği/lifecycle modeli henüz yoktur.

Bu nedenle mevcut `source_watch` yapay biçimde bir `job_id`/GoalState'e bağlanmayacaktır. Böyle bir bağlantı şu yeni ürün kararlarını gerektirir ve ayrı tasarım işi olarak ele alınmalıdır:

- subscription'ı hangi Core/Job oluşturur ve sahibi kimdir,
- subscription kimliği hangi `job_id`/`step_id`/owner ile bağlanır,
- `resume_token` ve `subject_version` nasıl üretilir ve saklanır,
- job `done/cancelled` olduğunda subscription nasıl kapanır,
- aynı kaynak birden fazla job tarafından izleniyorsa event fan-out nasıl yapılır,
- restart sonrası subscription nasıl yeniden yüklenir,
- watcher yalnız immutable RuntimeEvent üretirken global state kararını nasıl Core/Reducer'a bırakır.

## Gelecekteki hedef akış

```text
Durable Job/Core
→ subscription oluşturur ve kalıcı kimlik bağını saklar
→ watcher/source_watch yalnız immutable RuntimeEvent üretir
→ freshness + dedup + subscription/resume_token doğrulaması
→ runtime_event_commit
→ Core State Reducer + CAS
→ yalnız evidence kaydı
→ gerekiyorsa Core ayrı state/completion kararı verir
```

## Kapanış şartı

Bu madde ancak gerçek bir durable subscription modeli tanımlanıp en az bir production event kaynağıyla uçtan uca doğrulandığında kapatılır. Test-only `runtime_event_commit` kullanımı kapanış için yeterli değildir.

## Sıra ve sınırlar

1. Şimdilik `source_watch` davranışı değiştirilmez.
2. Durable subscription tasarımı, Organizer/runtime işi olarak kendi scope'u
   ve acceptance kriterleriyle açılır.
3. Event kendi başına `done`, `running` veya global completion kararı vermez;
   yalnız immutable evidence üretir.

Bu not yalnız durable RuntimeEvent producer entegrasyonunu izler. Diğer
hardening, ürün alanı ve migration kararları güncel kapanış/yol haritası
belgesinde ayrı tutulur.
