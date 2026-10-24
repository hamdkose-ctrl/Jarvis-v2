# Yol haritası notu — Aşama 4 sonrası ertelenen entegrasyonlar

**Durum:** Ertelendi / bilinçli mimari borç  
**Tarih:** 24 Ekim 2026

## Tamamlanan taban

Aşama 0–4 tamamlandı. Capability Manifest, explicit DecisionContext hattı,
GoalState Reducer/CAS, WorkerResult fencing, gerçek attempt sayacı, manifest
tabanlı effect journal ve üç kollu crash recovery main'dedir. Bu not yeni bir
execution engine veya ara çözüm önermek için değil, sıradaki mimari işleri
unutmadan doğru sırada açmak içindir.

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

## 1. Durable RuntimeEvent subscription — kapanış şartı

Bu madde ancak gerçek bir durable subscription modeli tanımlanıp en az bir production event kaynağıyla uçtan uca doğrulandığında kapatılır. Test-only `runtime_event_commit` kullanımı kapanış için yeterli değildir.

## 2. Conditional capability receipt sözleşmeleri

`browser` ve `coder` manifestte `conditional` + `reconciliation=required`
olarak tanımlıdır. Normal yol intent kaydını alır; worker doğrulanmış provider
receipt döndürürse receipt kalıcılaştırılır. Receipt sözleşmesi olmayan bir
provider crash sonrası güvenli biçimde `unknown` kalır ve kör retry yapmaz.

Gelecek iş, her effectful provider için receipt'in neyi kanıtladığını açıkça
sözleşmeye bağlamaktır. Provider accepted teslim/okunma kanıtı değildir.
Browser'da read-only ve effectful action ayrımı da worker çalışmadan önce
manifest politikasının belirlenmesini sağlayacak ayrı bir tasarımdır.

## 3. Canonical GoalState cutover

Mevcut compatibility adapter, legacy executor JSON kaydını korurken canonical
GoalState'i Reducer/CAS ile eşitler. Bu güvenli geçiş katmanıdır; nihai hedef
değildir. Cutover işi legacy kaydın gölge/uyumluluk görünümüne indirilmesini,
tek write authority'nin canonical GoalState olmasını ve doğrulanmış geri dönüş
planını gerektirir. Büyük-bang migration veya kontrolsüz dual-write yapılmaz.

## 4. Operasyonel repo koruması

`main` için PR, `testler-windows`, güncel-base ve force-push yasağıyla branch
ruleset tanımlanmıştır; ancak private Free repoda GitHub bunu enforce etmez.
GitHub Team/Pro'ya geçiş ayrı bir maliyet ve repository-transfer kararıdır.
Bu karar alınana kadar PR prosedürü, self-hosted Windows check, PC watcher ve
Main bekçisi birlikte koruyucu katman olarak kalır.

## Sıra ve sınırlar

1. Şimdilik `source_watch` davranışı değiştirilmez.
2. Durable subscription tasarımı, Organizer/runtime işi olarak kendi scope'u
   ve acceptance kriterleriyle açılır.
3. Receipt sözleşmeleri ve browser action ayrımı, subscription işine yapay
   bağımlılık kurulmadan ayrı capability hardening işleri olur.
4. Legacy GoalState cutover, yukarıdaki gerçek bypass/receipt belirsizlikleri
   kapandıktan sonra yapılır.

Bu maddeler Aşama 4'ü geriye dönük olarak eksik saydırmaz; mevcut korumalar
fail-closed kalır. Yeni işlerde bu not ve `JARVIS_STAGE_0_4_GUARD.md` birlikte
referans alınır.
