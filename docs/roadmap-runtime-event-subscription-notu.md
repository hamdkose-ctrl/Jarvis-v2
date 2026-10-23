# Yol haritası notu — Durable RuntimeEvent subscription entegrasyonu

**Durum:** Ertelendi / bilinçli mimari borç  
**Tarih:** 23 Ekim 2026

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

Bu not ancak gerçek bir durable subscription modeli tanımlanıp en az bir production event kaynağıyla uçtan uca doğrulandığında kapatılır. Test-only `runtime_event_commit` kullanımı kapanış için yeterli değildir.

## Öncelik

Şimdilik `source_watch` davranışı değiştirilmez. Önce 0–4 hardening işleri tamamlanır:

1. `specialist_orchestrator.run()` bypass'ını kapatmak veya replay-safe/read-only ile sınırlandırmak,
2. effect journal/crash recovery korumasını `publish` özelinden çıkarıp manifest tabanlı effectful capability'lere genellemek,
3. gerçek DecisionContext (`domain_invariant`, domain/user/job authority, `effect_state`) değerlerini runtime gate'e bağlamak,
4. ardından legacy GoalState dual-write geçişini daraltmak.

Bu subscription işi unutulmamalı; sonraki uygun roadmap aşamasında yeniden açılmalıdır.
