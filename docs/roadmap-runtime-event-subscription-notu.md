# Yol haritası notu — Durable RuntimeEvent subscription

**Durum:** Ertelendi / bilinçli mimari borç  
**Tarih:** 24 Ekim 2026

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
