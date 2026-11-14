# BRAIN-08 — tek PR uygulama ve kabul planı (14 Kasım 2026)

Taban: main `afcce500757340f88f15399aa1909e8842f8ff85` (#626 birleşti).
Yetki: Hamdi'nin “merge et ardından brain 8 planı çıkar aynı şekilde tek PR hallet” talimatı; plan ayrıca onay beklemeden aynı PR'da uygulanır.

## Karar ve iki seçenek

1. Yeni global approval deposu ve ayrı recovery yürütücüsü: mevcut pending, Outbox ve Core ile çift otorite oluşturur; seçilmedi.
2. **Mevcut sahipleri tamamlamak:** onay ExecutionRecord adımında, gönderim/idempotency mevcut Outbox SQLite'da, effect intent/receipt mevcut EffectJournal'da, lifecycle mevcut Core'da kalır. Seçilen yol budur.

## Koda bağlı açıklar ve uygulama

| Açık | Aynı PR'da iş | Kabul |
|---|---|---|
| Goal onayı yalnız waiting/approval_at ve native çıktıya dayanıyor | Opaque approval_id, owner/job/task, capability/input/target, plan digest/version, creation/expiry ve durable consumed kaydı; effect öncesi atomik tüketim | Owner/target/plan drift, expiry, duplicate ve iki süreç yarışında effect yok; bir onay bir attempt |
| Çıplak evet latest hedefe kayabilir | Bekleyen goal onaylarını gerçek owner deposundan say; tekil hedefi seç, birden fazla ise exact hedef kartını iste; foreground State sahipliği korunsun | İki onayda hiçbirinin çalışmaması, explicit job/snapshot'ın yalnız seçilen hedefe ulaşması |
| runtime_approved eski attempt'ten kalabilir | Onay cache'ini attempt sınırında temizle; resume effect yetkisi sayılmasın | Eski onayla yeni input/attempt çalışmaz |
| Outbox approval sınırsız yaşar; provider receipt biçimi tek başına yeterli görülüyor | Immutable payload/work key üzerinde süreli, tek tüketimli authorization; aynı SQLite send claim ile consume; doğrulanmış receipt yoksa unknown | Expiry/sending/unknown/duplicate gönderim yok; receipt-before-loss read-only recovery; Instagram bilinen container checkpoint'i korunur |
| Effect intent tekrar çağrısı sessizce kabul ediliyor | Mevcut journal ve per-job process lock üzerinden aynı command/operation için tekrar effect admission'ını reddet; recovery yalnız read-only | Attempt/version değiştirerek unknown replay yok; farklı gerçek adımlar birbirini engellemez |
| Batch kısmi ilerlemesi yalnız RAM'de | Mevcut service_store içinde request/action başına write-ahead checkpoint; tamamlanan adımlar korunur, interrupted running unknown kalır, aynı request replay edilmez | Disk/restart/partial/approval/cancel sırasında önceki başarıların tekrar yürümemesi |

## Korunan sınırlar

Yeni Scheduler, GoalState, capability, genel parser veya otomatik effectful DAG açılmaz. Native browser/desktop/file onayı ve JIT permission ayrıca zorunludur. Bir Core onayı native hedef onayının yerine geçmez. Genel provider exactly-once/forced cancellation garantisi verilmez; receipt bulunmayan dış effect unknown kalır. Trusted cross-owner OAuth subject olmayan bağlantılarda mevcut provider-wide fail-closed claim korunur; modelden, e-posta başlığından veya yerel owner adından subject uydurulmaz. Gerçek bağlantı/operatör/cihaz kabulü mocked regression ile kapatılmaz.

## Doğrulama ve teslim

Gerçek typed/bounded giriş, Core/disk/native adapter dikişlerinde sadece dış provider/OS sınırları taklit edilir. İki pending onay, seçili hedef, değişmiş input/plan, stale kart, expiry, tek kullanımlık consume, süreç yarışı, kayıp response/receipt, restart unknown ve partial batch ayrı regresyonlardır. Son kaynak full validation + Architecture Guard + roadmap drift/evidence; tek PR exact-head Windows CI + aynı SHA PC watcher. Başarılı kontrol yeni kaynak değişmedikçe tekrarlanmaz. Canlı effect göndermek test önkoşulu değildir.

## Uygulama bağlantısı ve kanıt sınırı

`goal_executor._record/_run/handle` → `goal_approval` → aynı per-job save/CAS; `goal_tools/task_workers/task_agents` → mevcut `outbox.dispatch` → aynı SQLite consume/send claim → mevcut provider adapter; `specialist_orchestrator` → `effect_recovery_runtime.record_intent` → mevcut EffectJournal/process lock. `core_brain_adapter._batch_handoff` mevcut service SQLite'a action başlamadan checkpoint yazar; request tekrarında sadece eski ilerlemeyi döndürür. Yeni pending executor veya otomatik batch resume kurulmaz; belirsiz started adım tekrar edilmez. Mevcut goal checkpoint/resume ve bağımsız task kuyruğu korunur. `publish_services.google_service` bounded AuthorizedHttp'ye taşınmıştır. Provider receipt şekli, provenance/domain authority ve kullanıcı okudu/duydu kanıtı birbirinden ayrıdır.

Yeni native/provider fake sınırlarıyla 18 regresyon: gerçek goal onay/tamamlanma, plan/target drift, expiry, iki pending + seçili kart, consume-save failure/thread ve iki gerçek process yarışı, Outbox unknown/yanlış target/no duplicate, receipt-before-final-write restart readback, provider-busy-before-consume, gerçek typed batch request replay ve partial checkpoint, effect attempt/version replay fence. Bu testlerin geçmesi canlı provider/external exactly-once veya fiziksel kabul değildir; final kaynak kanıtı PR üstünde tutulur.

Yerel kayıt ID'si tek başına target sürümü değildir: onay, gerçek owner profil kaydının digest'ini tutar; aynı ID'nin içeriği değişirse geçersizdir. Yerel mutasyon öncesi mevcut Profile RLock altında tekrar kontrol edilir. Gönderici bağlantısı için yalnız credential generation hash'i saklanır; access-token refresh geçersizleştirmez, refresh credential/native config değişimi onayı iptal eder. Gerçek Google credentials ve native config provider çağrısından hemen önce tekrar eşleştirilir; bu hash trusted OAuth subject iddiası değildir ve provider-wide fallback korunur. UI doğrudan goal_approval/batch checkpoint yazarı import edemez. Yeni approval kolonları mevcut SQLite writer transaction içinde göç eder.

### Effect receipt / Core CAS kesinti penceresi

Mevcut publish recovery artık yalnız Outbox'ın exact payload/owner receipt readback'i için `receipt_readback` kullanır. Kalıcı receipt bulunup Core WorkerResult henüz yazılmadıysa eski aynı owner/job/command/attempt/capability/input intent'i tekil olarak bulunur; lifecycle sürümü ilerlemiş olsa da yeni send başlatılmaz. Domain doğrulaması, kalıcı receipt referansı eşitliği ve güncel WorkerResult/CAS kabulü zorunludur. Core zaten aynı command'ı kabul ettiyse tekrar callback/append yoktur. Başka capability'ye provider reread/replay yetkisi verilmez; çelişen/çoklu receipt ve değiştirilmiş input/attempt reddedilir. İki yeni gerçek Core/Outbox regresyonu intent-only veya receipt-before-Core restart, sürüm ilerlemesi, idempotent evidence ve çelişen makbuz reddini sınar.
