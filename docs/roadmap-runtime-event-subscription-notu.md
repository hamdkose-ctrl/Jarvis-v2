# Yol haritası notu — Durable RuntimeEvent subscription

**Durum:** Kapandı (Faz 2-2, 26 Ekim 2026) — ilk production kaynak `source_watch`  
**Tarih:** 24 Ekim 2026, güncelleme 26 Ekim 2026

## Verilen kararlar (Faz 2-2)

Modül: `modules/runtime_event_subscription.py`. Test: `tests/test_runtime_event_subscription.py`.

- **Sahip:** Kaynak takibini (`monitor add`) çalıştıran hedef, yani `identity['job_id']`. Canonical GoalState yoksa veya hedef bitmişse abonelik açılmaz, takip yine eklenir.
- **Kalıcılık:** Hedef klasöründe `runtime_event_subscriptions.json` (abonelikler) ve `runtime_event_seen.json` (dedup). Bellekte durum tutulmaz; yeniden başlatmada aynı dosyalar okunur. Bozuk kayıt fail-closed reddedilir.
- **Kimlik alanları:** `source_event_key = source_watch:<kural>`. `source_generation`, aynı hedef/kaynak için her yeniden abonelikte bir artar. `subject_version`, bağlama anındaki GoalState sürümüdür (yalnız tazelik alanı, CAS sürümü değil). `resume_token` rastgele ve kalıcıdır. `fresh_after` abonelik zamanıdır; daha eski kaynak olayları bayat sayılır.
- **Olay:** `source_events` satırı → `runtime_event.v1`, `kind = source_watch.item_changed`. `event_id` abonelik ve kaynak olay kimliğinden türetilir; yeniden taramada aynı kimlik çıkar ve dedup edilir.
- **Akış:** `task_queue` döngüsü her `source_watch.poll` sonrası `pump_safely` çağırır; elle `monitor check` de aynısını yapar. `pump` → `runtime_event_commit` → Reducer `append_evidence` + CAS. CAS yarışında bir kez yeniden okur.
- **Yaşam döngüsü:** Hedef `done/cancelled` olursa, GoalState kaybolursa ya da takip kuralı silinirse abonelik `closed` olur (nedeni kaydedilir). Duraklatılmış kural olay üretmediği için abonelik açık kalır.
- **Fan-out:** Aynı kurala bağlı her hedef kendi aboneliğiyle ayrı evidence alır.
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
