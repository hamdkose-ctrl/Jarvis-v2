# Jarvis Effectful Worker Journal Matrix v1

## Amaç

Bu belge, gelecekteki effectful Worker/Adapter adaylarının hangi durumda mevcut `effect_journal` intent/receipt/reconcile sözleşmesini kullanması gerektiğini kaynak-doğrulanmış bir karar matrisi olarak sabitler. Yeni runtime, worker, journal, permission motoru veya ikinci capability kataloğu eklemez.

Kaynak kodda write-ahead recovery gereksiniminin kaynağı `modules/effect_recovery_runtime.required(kind)` fonksiyonudur. Bu fonksiyon ikinci bir katalog tutmaz; `modules/capability_manifest.py` içindeki mevcut manifest görünümüne bakar ve yalnız `replay == "conditional"` **ve** `reconciliation == "required"` olduğunda journal gerektirir. Dolayısıyla bu belge capability id uydurmaz; mevcut manifest davranışını ve henüz uygulanmamış gelecek alanlar için giriş koşullarını açıklar.

## Kaynak-doğrulanmış temel sözleşme

Mevcut kodun değişmez sınırları:

1. `modules/effect_journal.py` append-only `effect_intent.v1` ve doğrulanmış `effect_receipt.v1` kaydı tutar; journal effect çalıştırmaz, retry yapmaz ve reconcile yapmaz.
2. Intent kaydı `effect_id`, owner, job, command, capability id/version ve input digest ile dış etkiden **önce** kalıcılaştırılır. Persistent journal atomik yazımdan sonra bellekteki snapshot'ı ilerletir.
3. Receipt, intent olmadan kabul edilmez. `record_receipt()` bu durumda `ContractViolation("Intent kaydından önce dış etki bildirildi.")` üretir. Dış etki intent kaydından önce gerçekten oluşmuşsa aynı durum contract violation/fail-closed kabul edilir; sistem bunu başarılı yürütme diye meşrulaştıramaz.
4. `modules/crash_recovery.py` yalnız üç dallı saf karar verir:
   - `not_started` → `policy_required` / `EFFECT_INTENT_MISSING`
   - `unknown` → `read_only_reconcile` / `RECEIPT_MISSING_NO_BLIND_RETRY`
   - `succeeded` → `no_retry` / `VERIFIED_RECEIPT_PRESENT`
5. Crash recovery effect worker'ı tekrar çalıştırmaz. `unknown` dalında yalnız read-only reconcile yapılabilir. Reconcile yeni bir effect yaratacaksa recovery yardımcı yolu kullanılamaz; normal `Domain Invariant → Decision Authority → JIT Permission → Effect Policy → Worker/Adapter` hattına geri dönülür.
6. `modules/effect_recovery_runtime.py` yalnız doğrulanmış provider receipt'i (`service` + `remote_id`) journal'a yazar. Reconcile sonucu `done` ise bile önce WorkerResult fencing'den geçer, sonra mevcut Reducer/CAS commit yoluna verilir.
7. Worker veya reconcile çıktısındaki `done` global completion değildir. WorkerResult Core girdisidir; GoalState veya Completion Policy kararını doğrudan yazamaz.

## Journal gereksinimini belirleyen manifest alanları

`modules/capability_manifest.py` aşağıdaki alanları yayımlar: `permission_class`, `effect_policy`, `decision_authority`, `replay`, `reconciliation`, `evidence_contract`.

Mevcut eşlemelerde:

- `task.publish` → `external_write`, `ask_required`, `conditional`, `required`
- `task.browser` → `external_write`, `ask_required`, `conditional`, `required`
- `goal.desktop` → `physical_effect`, `ask_required`, `conditional`, `required`
- `message_out` sınıfı → `external_write`, `ask_required`, `conditional`, `required`
- `physical` sınıfı → `physical_effect`, `ask_required`, `conditional`, `required`
- diğer destructive sınıflar varsayılan olarak → `local_destructive`, `ask_required`, `conditional`, `required`
- `read` → `read_only`, `execute`, `safe`, `none`
- `local_reversible` → `local_reversible`, `execute`, `safe`, `none`

Bu nedenle journal kullanımı yalnız “yan etki var mı?” sorusuna bakılarak değil, manifestteki replay/reconciliation sözleşmesiyle belirlenir. Özellikle local reversible bir işlem mevcut manifestte `safe/none` ise bu v1 journal sözleşmesi otomatik olarak zorunlu değildir; aynı işlem overwrite/destructive sınıfa yükseliyorsa `conditional/required` olur ve journal gerekir.

## Effectful Worker journal matrisi

| Alan / eylem | Yan etki mi? | Intent zorunlu mu? | Receipt nedir? | Crash sonrası üç-dal davranışı | Read-only reconcile mümkün mü? | Blind retry yasak mı? | JIT Permission / Decision Authority |
|---|---|---|---|---|---|---|---|
| **Publish** (`task.publish`) | Evet, dış sisteme yazma/yayın | **Evet.** Manifest `conditional + required`; provider effect başlamadan önce durable intent | Sağlayıcının doğrulanabilir yayın kimliği; recovery runtime biçiminde `service + remote_id` | intent yok → policy hattına dön; intent var receipt yok → read-only sağlayıcı sorgusu; receipt var → retry yok | Sağlayıcı yayın durumunu yazmadan okuyabiliyorsa evet | **Evet** | `ask_required`; effect öncesi Decision Authority + JIT Permission + Effect Policy zorunlu |
| **Browser action** (`task.browser` effectful action) | Evet. Click/fill/submit vb. dış veya yerel etkili olabilir | **Evet** effectful browser case'inde; mevcut manifest `external_write / conditional / required` | Hedef sistemin doğrulanabilir işlem/nesne kimliği varsa provider receipt; receipt sözleşmesi yoksa state `unknown` fail-closed kalır | üç dal aynen uygulanır; unknown durumda browser action tekrar oynatılmaz | Yalnız sayfa/remote durumunu değiştirmeyen sorgu ile mümkünse | **Evet** | `ask_required`; normal policy zinciri atlanamaz |
| **Computer click/type** (`goal.desktop` effectful fiziksel UI eylemi) | Evet, fiziksel/UI etkisi | **Evet** manifest `physical_effect / conditional / required` olduğu effectful yürütmede | Uygulamanın doğrulanabilir sonucu/remote id'si varsa receipt; yoksa yalnız intent varlığı nedeniyle crash sonrası `unknown` kalabilir | not_started → policy; unknown → yalnız read-only UI/state gözlemi; succeeded → no retry | UI durumunu değiştirmeden gözlem yapılabiliyorsa kısmen | **Evet** | `ask_required`; fiziksel sınıf JIT onaysız yürütülemez |
| **File write / delete / move** | Yazma/overwrite/delete/move yan etkidir | **Koşullu.** Salt yeni ve gerçekten `local_reversible/safe/none` olarak manifestlenmiş işlemde mevcut journal zorunlu değil. Overwrite/delete/destructive move gibi `local_destructive / conditional / required` sınıfta **zorunlu** | Dosya sistemindeki kalıcı sonuç kimliği/digest/target state; gerçek doğrulanabilir receipt sözleşmesi capability tarafından tanımlanmalı | journal-required sınıfta üç dal aynen; intent yoksa yeni yazma başlatılmaz, unknown'da yalnız dosya durumunu okuyan reconcile, succeeded'da retry yok | Path/metadata/digest yalnız okunarak doğrulanabiliyorsa evet | Journal-required destructive sınıfta **evet** | Destructive sınıfta `ask_required`; local reversible sınıfın mevcut manifest authority'si `execute` olabilir. Sınıflandırma önceden kesin olmalı |
| **Communication send** (`message_out`) | Evet, dış alıcıya gönderim | **Evet.** Manifest eşlemesi `external_write / conditional / required` | Gmail/Telegram/WhatsApp vb. sağlayıcının doğrulanmış message/remote id'si | intent yok → policy; receipt yok → read-only “mesaj gerçekten gitti mi?” reconcile; receipt var → no retry | Sağlayıcı mesaj geçmişini yalnız okuyarak kesin hedef/id ile doğrulayabiliyorsa evet | **Evet** | `ask_required`; kesin alıcı/target JIT permission ile tekrar doğrulanmalı |
| **Finance transaction** | Gelecekte gerçek para/emir etkisi olursa evet; **bugün uygulanmış capability değildir** | Bugünkü repo bunu çalıştırmaz. Gelecekte açılabilmesi için yeni manifest kaydı `conditional + required`, idempotency ve journal sözleşmesi tasarlanmalı; bu koşullarda **evet** | Banka/aracı kurum/cüzdan tarafından doğrulanabilir transaction/order id; sadece model metni receipt değildir | Gelecek capability aynı üç-dal kontratını kullanmalı; unknown durumda para hareketi kör tekrar edilmez | Sağlayıcının durum sorgusu yazmadan yapılabiliyorsa zorunlu tercih | **Kesinlikle evet** | Finance karar kaydına göre bugün `money_credential` kapalıdır. Gelecekte Decision Authority + JIT Permission + Effect Policy + canlı acceptance olmadan açılamaz |
| **Future Hermes / external skill effect** | Dış skill gerçekten etki yaratıyorsa evet | Otomatik değil; önce Jarvis manifest/policy binding'i gerekir. Binding `conditional + required` ise **evet**. Dış skill kendi journal'ını otorite yerine koyamaz | Jarvis'in doğrulayabildiği provider/target receipt; skill'in “success” metni tek başına receipt değildir | Jarvis Core üç-dal recovery kararını verir; dış agent kendi başına retry/reconcile/effect kararı veremez | Ayrı read-only reconcile adapter'ı gerçekten side-effect üretmiyorsa evet | **Evet** | Dış skill authority değildir; Domain Invariant → Decision Authority → JIT Permission → Effect Policy hattı zorunlu |

## Üç-dal recovery ayrıntısı

### 1. `not_started` — intent yok

Journal `not_started` döndürüyorsa Core dış etkinin hiç başlamadığını varsayarak doğrudan worker çağırmaz. `crash_recovery.decide()` sonucu `policy_required / EFFECT_INTENT_MISSING` olur. Yeni effect gerekli görülüyorsa karar **baştan normal policy hattına** girer ve yeni, geçerli bir JIT permission olmadan başlayamaz.

Intent kaydı bulunmadan sağlayıcıda dış etkinin oluştuğuna dair veri görülmesi bir başarı kestirmesi değildir; write-ahead contract ihlalidir ve fail-closed ele alınır. Böyle bir durum için receipt sonradan “uydurularak” intent zinciri tamamlanmaz.

### 2. `unknown` — intent var, doğrulanmış receipt yok

Bu en kritik crash aralığıdır: dış etki hiç oluşmamış da olabilir, olmuş ancak receipt kalıcılaşmadan süreç çökmüş de olabilir. Bu nedenle `RECEIPT_MISSING_NO_BLIND_RETRY` kuralı geçerlidir.

İzin verilen tek ilk adım read-only reconcile'dır. Reconcile:

- aynı owner/job/command/capability/input fence'ine bağlı olmalı,
- dış sisteme yeni yazma yapmamalı,
- yalnız mevcut remote/local durumu okumalı,
- effect gerçekten olmuşsa doğrulanabilir provider receipt döndürmeli,
- sonucu WorkerResult fencing üzerinden Core'a vermelidir.

Reconcile sırasında “kontrol etmek için tekrar gönder”, “yeniden click et”, “dosyayı tekrar yaz”, “emri yeniden ver” gibi yeni yan etki gerekiyorsa reconcile durur; normal policy zincirine geri dönülür.

### 3. `succeeded` — doğrulanmış receipt var

Receipt varsa effect'in gerçekleştiği doğrulanmıştır. Recovery `no_retry / VERIFIED_RECEIPT_PRESENT` döndürür. Provider tekrar çağrılmaz ve receipt global completion olarak yorumlanmaz. Goal/Job tamamlanması yine Reducer/CAS + Completion Policy tarafından belirlenir.

## Receipt ne değildir

Aşağıdakiler tek başına doğrulanmış receipt sayılmaz:

- worker'ın `success` veya `done` demesi,
- model cevabı,
- UI'da beklenen metnin görünmesi ama hedef/kimlik bağının olmaması,
- “muhtemelen gönderildi/yazıldı” tahmini,
- salt duration veya log mesajı,
- dış skill'in kendi iç başarı bayrağı.

Mevcut `effect_recovery_runtime._receipt_ref()` somut olarak `receipt.service` ve `receipt.remote_id` ister. Capability'nin sağlayıcısı bu biçimde doğrulanabilir kimlik veremiyorsa journal intent yine crash belirsizliğini gösterir, fakat recovery fail-closed `unknown` kalabilir; bu durum kör retry izni değildir.

## WorkerResult ve global completion sınırı

Effect journal, effect'in execution/recovery kanıtıdır; GoalState yazarı değildir. Reconcile'dan elde edilen `done` gözlemi önce `worker_result_hook.wrap_output()` ile immutable execution fence'e bağlanır, sonra `runtime_worker_result.accept_and_commit()` üzerinden mevcut Reducer/CAS yoluna girer.

Bu nedenle:

- **worker done ≠ global completion**,
- **receipt present ≠ global completion**,
- **reconcile done ≠ global completion**.

Completion Policy ayrı Core otoritesidir.

## Finance ve external skill için özellikle geçerli sınır

Finance'in bugünkü kaynak-doğrulanmış kapsamı read-only analizdir; banka/aracı kurum/cüzdan bağlama, emir, alım-satım veya para transferi mevcut capability değildir. `money_credential` kapalıdır. Bu matristeki finance transaction satırı yalnız gelecekteki effectful capability'nin kabul koşuludur; var olan bir işlem yolu iddiası değildir.

Hermes veya başka external skill de doğrudan Core authority olamaz. Önce Jarvis capability manifest binding'i, permission/effect sınıfı, replay/reconciliation politikası ve evidence/receipt contract tanımlanır. Dış runtime'ın kendi retry mekanizması Jarvis'in blind-retry yasağını aşamaz.

## Contract violation / fail-closed koşulları

Aşağıdakilerden biri varsa effect güvenli başarı sayılamaz:

- dış etki durable intent kaydından önce başladı veya oluştu;
- journal-required capability intent yazmadan worker/provider çağırdı;
- receipt intent ile aynı `effect_id`'ye bağlı değil;
- receipt doğrulanmış değil veya provider kimliği yok;
- crash sonrası unknown state blind retry ile yeniden yürütüldü;
- reconcile read-only olmaktan çıkıp yeni effect oluşturdu;
- WorkerResult fence owner/job/step/command/attempt/version/capability/input digest ile uyuşmuyor;
- worker/skill receipt veya `done` değerini global completion diye yazmaya çalışıyor;
- JIT permission/Decision Authority gereken capability bu hattı atlıyor.

Bu ihlallerde varsayılan davranış fail-closed'dur; sessiz downgrade veya tahmini başarı yoktur.

## Kapsam dışı

Bu belge şunları eklemez veya değiştirmez:

- yeni effect journal veya recovery runtime,
- yeni worker/provider/adapter,
- publish/browser/desktop/outbox/finance kodu,
- yeni finance transaction capability,
- Hermes/external skill importu,
- GoalState/reducer/Completion Policy,
- Permission Gate veya Effect Policy uygulaması,
- capability manifest alanları,
- CI/workflow/watcher/test/fixture.

Amaç yalnız mevcut journal/recovery sözleşmesini effectful worker ailelerine kaynak-doğrulanmış ve fail-closed bir karar matrisi olarak uygulamaktır.
