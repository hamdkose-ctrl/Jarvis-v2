# Jarvis Otonom / Serbest Runtime v1.1 — Canonical Tasarım

Tarih: 2 Kasım 2026
Durum: **DESIGN FROZEN — IMPLEMENTATION NOT STARTED**
Başlama kapısı: **Faz 0–4 gerçek closeout + Canonical Brain closeout**

Bu belge mevcut fazların yerine geçen yeni bir roadmap değildir. Otonom/Serbest, mevcut Core/GoalState/RuntimeEvent/worker altyapısının üstüne gelen **yatay çalışma katmanıdır**.

## 1. Ürün amacı

Jarvis'in amacı en fazla güvenlik kontrolüne sahip sistem olmak değildir.

Amaç:

> Kullanıcının verdiği hedefi gerçekten ilerleten, gereksiz yere soru sormayan, kendi başına iş yapabilen, sonucu geldikçe gösteren, çalışırken yönlendirilebilen ve kontrolü kullanıcıda bırakan dijital bir sağ kol üretmek.

Üç ölçüt birlikte korunur:

1. kalite,
2. hız,
3. kullanım hazzı.

Ana ilke:

> **Mümkünse ilerle; gerçekten gerekli yerde frenle.**

Güvenlik; para, authority, veri çıkışı, geri döndürülemez dış etki ve kullanıcı kontrolü gibi gerçek sınırları korur. Güvenlik Jarvis'in hiçbir şey yapmamasının bahanesi değildir.

## 2. Kullanıcı modları

Yalnız iki autonomy modu vardır:

- `OTONOM`
- `SERBEST`

### OTONOM

Kullanıcı hedefi verir; Jarvis hedefi kendi yürütür. Subgoal oluşturabilir, worker seçebilir, başarısız izinli yöntemi değiştirebilir, bekleyebilir, event/timer sonrası yeniden uyanabilir ve restart sonrası devam edebilir.

### SERBEST

OTONOM + sınırlı ajan organizasyonudur. Direct child'lar, sibling subgoal'lar ve bounded paralel/sıralı delegation kullanılabilir.

> **Serbest = daha geniş inisiyatif; daha geniş authority değildir.**

V1 delegation modeli düzdür:

```text
Jarvis/Core  depth 0
  ├─ Research Child  depth 1
  ├─ Analysis Child  depth 1
  └─ Verify Child    depth 1
```

`MAX_DELEGATION_DEPTH = 1`.

Child başka uzman isterse Core'a proposal döndürür; Core yeni **sibling** subgoal/child açabilir. Child doğrudan child oluşturmaz.

## 3. Authority anayasası

```text
Brain       -> anlar / bağlam kurar / plan ve capability önerir
Worker      -> result / evidence
Child       -> proposal / result / evidence
Watcher     -> event
Runtime     -> wake

Core        -> authority / permission / budget / provider / risk / effect
Reducer/CAS -> canonical state
Completion  -> global completion kararı
```

Brain, Worker ve Child:

- permission oluşturamaz veya genişletemez,
- GoalState'i doğrudan yazamaz,
- Reducer/CAS'i bypass edemez,
- provider allowlist değiştiremez,
- veri sınıfını düşüremez,
- kendi budget'ını artıramaz,
- global `COMPLETE` ilan edemez,
- external effect'i doğrudan başlatamaz.

Ana kural:

> **Brain düşünür ve önerir; Core yetkilendirir.**

## 4. Canonical giriş ve continuation

Yeni kullanıcı isteği canonical Brain hattından geçer:

```text
USER MESSAGE
 -> ActiveContext
 -> Exact State Gate
 -> Deterministic Fast Gate
 -> Candidate Builder
 -> Reference Resolver
 -> Understanding
 -> Brain proposal
 -> Core
```

Devam eden Goal için Brain'den önce deterministik continuation kontrolü vardır:

```text
Timer / Event / WorkerResult / Resume
        ↓
Continuation Controller
        ↓
actionable?
  ├─ hayır -> NO_ACTION
  └─ evet  -> ContinuationContext -> Brain -> Proposal -> Core
```

Her heartbeat modeli uyandırmaz.

## 5. Wake nedenleri ve duplicate coalescing

Canonical wake nedenleri:

- `USER_MESSAGE`
- `TIMER`
- `EVENT`
- `WORKER_COMPLETE`
- `DEPENDENCY_READY`
- `RETRY_DUE`
- `APPROVAL_RECEIVED`
- `QUOTA_RESET`
- `RESTART`
- `MODE_CHANGED`
- `PERMISSION_CHANGED`
- `CREDENTIAL_EXPIRED`
- `SYSTEM_RESUME`

Kontrol komutları (`PAUSE_REQUESTED`, `CANCEL_REQUESTED`) Brain reasoning beklemeden Core kontrol yoluna gider.

Aynı Goal için eşzamanlı wake'ler `goal_id + expected_version + wake_generation` ile tek değerlendirmeye coalesce edilir.

## 6. Pause / Resume / Cancel — autonomy'den önce gelir

Autonomous continuation açılmadan önce bu kontrol yolu hazır olmalıdır.

- `Jarvis dur` -> `PAUSED`
- `Devam et` -> revalidation sonrası resume
- `İptal et` -> terminal `CANCELLED`

Pause sırasında:

- yeni child/worker/continuation başlamaz,
- mümkün olan running work safe-cancel edilir,
- canonical state/evidence silinmez,
- gelen event/timer kaybolmaz; bounded olarak biriktirilir/coalesce edilir ve resume'da tek değerlendirmeye girer.

Pause sırasında wall-clock tabanlı gerçek deadline, approval expiry ve quota reset ilerlemeye devam eder. Active execution TTL ise PC uyku/pause süresini çalışma süresi saymaz.

Unknown external effect resume'da kör retry edilmez; önce read-only reconcile edilir.

## 7. Mid-Flight Steering

Kullanıcı çalışan Goal'a rota düzeltmesi verebilir:

- “sadece Türkiye'ye bak”,
- “yabancı kaynakları bırak”,
- “şu siteyi kullanma”,
- “fiyat tarafını da ekle”.

Akış:

```text
USER_MESSAGE
 -> STEER_CURRENT_GOAL proposal
 -> Core doğrulama
 -> constraint update
 -> goal_version++
 -> artık geçersiz branch/child stop/stale
 -> continuation
```

Steering:

- mevcut geçerli evidence'i silmez,
- permission/budget/data-egress yetkisini genişletemez,
- belirsizse mevcut Goal'ı yıkıcı biçimde değiştirmek yerine clarify/new-request ayrımı yapılır.

`STEER_CURRENT_GOAL` ile bağımsız `NEW_REQUEST` aynı şey değildir.

## 8. Streaming Artifacts ve micro-feedback

Kullanıcı finali beklemek zorunda değildir. Canonical state'e commit edilmiş, evidence referansı taşıyan anlamlı ara çıktılar UI'da **partial artifact** olarak gösterilebilir.

Partial artifact:

- final sonuç gibi sunulmaz,
- varsa henüz semantic verification geçmediği açıkça işaretlenebilir,
- panelde güncellenmesi notification yağmuru üretmez.

Proaktif notification yalnız:

- kullanıcı kararı gerektiğinde,
- yeni ciddi blocker oluştuğunda,
- anlamlı milestone/sonuç gerektiğinde,
- final completion'da

üretilir. Aynı blocker tekrar bildirilmez.

Mid-flight steering ve ilk anlamlı ara sonuç için kısa micro-feedback kullanılır:

> “Anlaşıldı, yabancı kaynakları çıkarıp sadece Türkiye verisiyle devam ediyorum.”

> “İlk iki kaynağı doğruladım, ekrana bıraktım; üçüncüsüne bakıyorum.”

Heartbeat / “hâlâ çalışıyorum” micro-feedback değildir.

## 9. Brain proposal ve bozuk çıktı

Continuation proposal türleri:

- `CONTINUE`
- `DELEGATE`
- `CREATE_SUBGOAL`
- `WAIT`
- `ASK_USER`
- `FINISH_PROPOSAL`

Bozuk JSON/schema, olmayan capability veya uydurma worker effect başlatamaz.

V1 davranışı:

1. bir bounded repair/retry,
2. uygunsa başka izinli provider,
3. hâlâ invalid ise `BRAIN_OUTPUT_INVALID / WAIT`.

Her deneme Goal budget'ından düşer. Provider değişirse privacy/data-egress/free-tier/quota kapıları baştan çalışır.

## 10. Repeated proposal loop breaker

Core şunları izler:

- `proposal_fingerprint`
- `reject_reason`
- `relevant_precondition_digest`

Aynı koşulda aynı proposal iki kez reddedilirse yöntem `SUPPRESSED` olur. Goal hemen BLOCKED yapılmaz; başka uygun yol denenebilir. Suppression rastgele süreyle değil, ilgili state/precondition değişince kalkar.

## 11. Budget authority ve profiller

Budget yalnız Core authority'sidir. Child/worker tüketimi parent Goal budget'ından harcanır.

Başlangıç profilleri:

| Profil | Brain turn | Worker komutu | Aktif çalışma | Toplam child |
| --- | ---: | ---: | ---: | ---: |
| Küçük | 4 | 6 | 15 dk | 1 |
| Orta | 8 | 16 | 60 dk | 3 |
| Büyük | 16 | 40 | 4 saat | 6 |

Serbest V1 sınırları:

- `MAX_PARALLEL_CHILDREN = 2`
- `MAX_PARALLEL_CLOUD_LLM = 1`
- `MAX_DELEGATION_DEPTH = 1`

Cloud LLM concurrency=1 olduğu için iki child'ın cloud reasoning'i serialize olabilir; gerçek paralellik local model/read-only/network/file/CPU işlerinde görülebilir.

Budget artışı yalnız gerçek authenticated user command/UI Core command ile olur. Brain yalnız extension önerebilir.

### Grace Turn

Meaningful progress varsa Core bir defaya mahsus **+2 grace turn** kullanabilir. Bu kullanıcı budget artışı değildir; önceden tanımlı bounded completion rezervidir. Loop/repeated rejection/progress yoksa grace verilmez.

Budget tamamen biterse:

```text
kanıt/state korunur
 -> partial result kullanıcıya
 -> WAITING_FOR_BUDGET
```

## 12. Uzun takip işleri

“Yeni model çıkınca haber ver” gibi Goal'lar beklerken active budget tüketmez. Her gerçek wake küçük ayrı execution slice alır.

> `WAITING != active execution`

## 13. Meaningful progress ve TTL

Heartbeat, “çalışıyorum”, aynı log/evidence progress değildir.

Meaningful progress:

- yeni kabul edilmiş evidence,
- yeni WorkerResult,
- tamamlanan subgoal,
- çözülen blocker,
- canonical state'in gerçek ilerlemesi.

Child lifecycle:

- `progress_lease`
- `active_execution_ttl`

PC suspend süresi active execution sayılmaz. Gerçek deadline/approval expiry/quota reset wall-clock ile ilerler.

## 14. CompletionPolicy ve hızlı bitiş

Goal başında ölçülebilir completion kriterleri saklanır.

Core ölçebilir:

- kaynak sayısı,
- tarih/freshness evidence,
- URL/evidence varlığı,
- artifact varlığı,
- required worker completion,
- blocker/conflict durumu.

Semantic verifier authority değildir; yalnız evidence üretir.

Small/Medium işte deterministik şartlar geçmiş, conflict ve low-confidence flag yoksa **ek LLM verifier çağrısı yapılmadan sonuç anında tamamlanabilir**.

Semantic verifier yalnız Large, conflict, düşük güven veya özellikle kalite doğrulaması gereken işte kullanılır ve Goal budget'ından düşer.

Research'te kaynak sayımı yalnız link sayısına indirgenmez; mümkün olduğunda bağımsız source/domain ve mevcut güvenilir freshness metadata kullanılır. Şüpheli/çelişkili durumda verification yükseltilir; her küçük araştırmaya ağır provenance zinciri zorunlu değildir.

## 15. Assumption Ledger

Düşük riskli ve geri alınabilir kararlarda Jarvis makul varsayımla ilerleyebilir; önemli varsayımı `assumptions_used` içinde kaydeder ve final/ilgili ara sonuçta kısa biçimde görünür kılar.

Brain “düşük risk” diyerek sınırı değiştiremez. Risk sınıfı Core Effect/Risk Matrix'ten gelir.

Asla tahmin edilmeyecek örnekler:

- recipient,
- payment amount,
- account,
- file-to-delete,
- external destination,
- permission scope,
- credential.

## 16. Approval Matrix

Approval domain adına göre blanket uygulanmaz; işlem/effect sınıfına göre Core tablosundan gelir.

Tipik approval istemeyen işler:

- araştırma,
- web/dosya okuma,
- analiz/karşılaştırma,
- local reasoning,
- read-only worker,
- Jarvis workspace içinde yeni çıktı artifact'i.

Approval gerektiren tipik effect'ler:

- mevcut dosyayı overwrite/delete,
- dışarı mesaj/mail gönderme,
- para/broker/order,
- external system write,
- geri alınması zor effect,
- policy dışı data egress.

Kullanıcının aynı exact operation için geçerli, doğrulanmış komutu mevcut permission/effect sözleşmesine göre JIT approval yerine geçebiliyorsa gereksiz ikinci onay sorulmaz. Yüksek riskli domain'ler mevcut kendi domain sözleşmelerini korur; blanket “her zaman ekran onayı” autonomy katmanının genel kuralı değildir.

Sesli ve yazılı user command aynı Core effect matrix'ten geçer. Gerekli yerde stronger confirmation mevcut permission policy tarafından istenebilir; autonomy katmanı bütün voice komutlarını otomatik güvensiz saymaz.

`User silence != approval`.

Approval metninin effect/target/scope/fingerprint kısmı Core tarafından üretilir; Brain anlamını yumuşatamaz/değiştiremez.

Approval expiry spam üretmez. Late approval deterministik staleness check sonrası yeni fingerprint ile kullanılabilir.

## 17. Data classification

Temel sınıflar:

- `PUBLIC`
- `PRIVATE`
- `RESTRICTED`

Source-origin başlangıç kuralları:

| Kaynak | Başlangıç sınıfı |
| --- | --- |
| doğrulanmış halka açık web/news/public page producer | PUBLIC |
| yerel dosya / mail / takvim / özel artifact | PRIVATE |
| token / parola / secret / credential | RESTRICTED |
| normal kullanıcı hedef metni | normal conversation policy; private source içeriği/secret taşıyorsa ilgili sınıf yükselir |
| sınıfı belirlenemeyen derived/untrusted içerik | PRIVATE |

Brain kendi başına privacy sınıfını düşüremez.

## 18. LOCAL READ != DATA EGRESS

Özel veriyi yerelde okumak ile dışarı göndermek farklı operation'dır.

Data Egress yalnız model çağrısı değildir. Şunların tamamı outbound sayılır:

- LLM/model call,
- HTTP request body/header içeriği,
- URL/query parameter,
- **arama motoru sorgusu**,
- form submission,
- upload,
- email/message,
- webhook,
- external API write.

Her outbound operation Core Egress Gate'ten geçer:

`destination + purpose + data_class + operation_type + provider/service policy + permission`.

Web sayfası veya Brain, özel veriyi query/form/URL içine koyarak kapıyı bypass edemez.

## 19. Taint propagation

Derived data kaynak gizliliğini miras alır:

```text
PRIVATE source -> summary/projection -> PRIVATE
RESTRICTED source -> derived result -> RESTRICTED
```

Birden fazla kaynağın birleşiminde en kısıtlayıcı sınıf korunur.

Compact projection da bu kurala tabidir; privacy bypass aracı değildir.

## 20. Credential kuralı

Credential/secret:

- Brain context'e/model/evidence'e gitmez,
- URL/query/form'a yazılmaz,
- keyfi hedefe gönderilmez,
- log/error çıktısında sızdırılmaz.

Tek izinli kullanım, credential-aware transport tarafından kendi yetkili servisine authentication amacıyla kullanılmasıdır. Bu exception prompt/Brain tarafından genişletilemez.

## 21. External content / prompt injection

Web/PDF/mail/tool çıktısı `UNTRUSTED_DATA`'dır. İçindeki “şunu yap / dosyayı gönder / önceki talimatı unut” ifadesi permission, system instruction veya Core authority kazanamaz.

External data normal araştırmada kullanılabilir; sırf dış kaynaktan geldi diye araştırma durdurulmaz.

## 22. Provider / quota

Provider selection authority Brain'de değildir.

Bir cloud provider için birlikte geçerli olmalıdır:

- provider allowed,
- data class allowed,
- privacy evidence valid,
- free-tier evidence valid,
- quota available.

Provider fallback privacy/data-egress kararını miras almaz; her candidate için policy yeniden değerlendirilir.

Kesin invariant:

> **Quota exhausted != paid fallback.**

Local yoksa izinli ücretsiz cloud kullanılabilir. Ücretsiz quota da bittiyse `WAITING_FOR_QUOTA`.

Quota reset authoritative `reset_at`/Retry-After/header/verified policy ile biliniyorsa wake planlanır; polling yapılmaz.

Aynı credential/account birden fazla owner tarafından kullanılıyorsa gerçek quota authority credential/provider-account scope'tadır; owner kullanım muhasebesi ayrıca tutulabilir.

## 23. Notification policy

Partial artifact panel güncellemesidir; her partial result ayrı sistem notification üretmez.

Notification yalnız anlamlı yeni milestone, user decision, yeni ciddi blocker veya completion için üretilir. Aynı `blocker_fingerprint` değişmedikçe tekrar gönderilmez.

## 24. SubGoal != Child

`SubGoal` durable yapılacak iştir; `Child` geçici execution actor'dür. Child ölürse SubGoal kaybolmaz. Evidence önce bağlı subgoal'a, sonra parent Goal'a roll-up edilir.

## 25. Mode değişimi

### OTONOM -> SERBEST

Goal devam eder; yeni direct-child/delegation yetenekleri açılır.

### SERBEST -> OTONOM

- yeni child/delegation kapanır,
- mevcut child yalnız mevcut bounded command'ını tamamlayabilir,
- yeni subgoal/delegation alamaz,
- late/stale sonuç normal fencing'den geçer.

## 26. Unknown external effect

```text
UNKNOWN_EFFECT
 -> read-only reconcile
 -> doğrulanırsa state commit
 -> doğrulanamazsa BLOCKED_NEEDS_USER
```

Automatic blind retry yasaktır.

## 27. Restart / node

Restart sonrası GoalState, mode, budget, approvals, quota, child leases, pending effects ve wake state yeniden değerlendirilir.

Goal gerektiğinde `owner_id + origin_node_id + execution_affinity` taşır. Gerekli PC kapalıysa `WAITING_FOR_NODE`; UI açık neden gösterir. İlk sürümde karmaşık multi-PC migration yoktur.

## 28. Context compaction

Canonical evidence/history silinmeden bounded `CompactProjection + RecentEvidence` Brain context'i üretilebilir.

- projection authority değildir,
- compaction evidence deletion değildir,
- projection source privacy'sini miras alır.

Kullanıcının veri silme/retention ihtiyacı mevcut data lifecycle/cleanup sözleşmesine bağlanır; autonomy v1 içinde ikinci bağımsız storage authority kurulmaz.

## 29. Status UI

UI business authority taşımaz. Read-only panel en az şunları gösterebilir:

- Mode
- Goal
- Current step
- Partial results
- Waiting reason
- Last meaningful progress
- Active child count
- Remaining budget
- Provider/quota
- Pending approval
- Origin node

Kontroller (`DURDUR`, `DEVAM`, `İPTAL`, OTONOM/SERBEST, budget extension request) Core command üretir.

## 30. Bilerek yapılmayacaklar

Jarvis:

- kullanıcı sessiz diye third-party contact başlatmaz,
- kendi permission/budget/capability alanını büyütmez,
- ücretli modele sessiz geçmez,
- approval spam'i yapmaz,
- child üzerinden Core bypass etmez,
- unknown effect'i blind retry etmez,
- private/restricted veriyi policy dışında çıkarmaz,
- external content'i instruction authority saymaz,
- ikinci scheduler/reducer/permission/completion authority kurmaz.

## 31. Temel invariants

```text
Brain != authority
Worker != authority
Child != authority
AutonomyMode != permission
Serbest != unlimited
User silence != approval
Quota exhausted != paid fallback
Quota wait != polling
Read-only != unrestricted egress
Search query == outbound data
External content != instruction authority
Child budget == parent budget
Heartbeat != progress
Brain finish != Core completion
Unknown effect != blind retry
Compaction != evidence deletion
Summary privacy >= source privacy
Pause != Cancel
Duplicate wake != duplicate reasoning
Steering != permission/budget/privacy expansion
```

## 32. V1 acceptance

### Otonom temel

- normal autonomous Goal
- pause -> event arrives -> resume, event kaybolmaz
- cancel
- duplicate wake coalescing
- malformed Brain output
- repeated rejected proposal
- budget exhaustion -> partial result -> `WAITING_FOR_BUDGET`
- grace turn bounded
- quota exhausted -> wait -> resume
- restart during Goal
- sleep/resume
- streaming partial artifacts without notification flood
- mid-flight steering
- yanlış sınıflanmış steering evidence'i silmez
- late approval staleness
- unknown effect no blind retry

### Privacy / injection

- web prompt injection cannot gain authority
- private data -> URL/query/form exfiltration BLOCK
- private-derived **search query** egress BLOCK unless policy explicitly permits
- private source -> summary/projection -> unauthorized cloud BLOCK
- wrong-provider fallback BLOCK
- credential -> model/arbitrary HTTP/log BLOCK
- credential -> own authorized auth transport ALLOW

### Research completion

- obviously stale/contradictory evidence cannot satisfy completion merely by link count
- source/domain independence is used where the task requires independent evidence
- suspicious date/freshness evidence raises verification instead of silently claiming certainty

### Serbest

- direct child delegation
- two sibling children
- parent-budget accounting
- cloud LLM concurrency=1
- child cannot spawn child
- child asks Core for sibling specialist
- Otonom <-> Serbest mode changes
- stale/late child result rejected

### Gerçek Windows/PC

- ComputerWorker via Core
- permission bypass BLOCK
- pause/resume/cancel
- stale result reject
- node offline -> `WAITING_FOR_NODE`
- restart recovery
- unknown PC effect no blind retry

Serbest gerçek-PC acceptance olmadan tamam sayılmaz.

## 33. Uygulama sırası ve paket isimleri

**Ön koşul:** Faz 0–4 gerçek closeout + Canonical Brain closeout.

Mevcut repo PR numaralarıyla karışmaması için autonomy işleri `OTO-*` ve `SER-*` paket adlarıyla takip edilir. Bunlar roadmap çalışma paketleridir; diff büyürse daha küçük PR'a bölünebilir, fakat authority sınırları tek PR'da birbirine karıştırılmaz.

### OTONOM

1. **OTO-1 — Mode + Control Plane:** AutonomyMode, Pause/Resume/Cancel, stop gate ve temel invariants. Autonomous wake bundan önce açılmaz.
2. **OTO-2 — Risk / Privacy / Egress contracts:** Effect/Risk Matrix, source classification, taint propagation, credential/log redaction, outbound/search-query egress gate.
3. **OTO-3 — ContinuationWake + Controller:** deterministic precheck, wake seti, paused event retention, duplicate coalescing.
4. **OTO-4 — Budget:** profiles, parent accounting, grace reserve, partial-result-on-exhaustion.
5. **OTO-5 — Quota-aware runtime:** provider/account quota scope, WAITING_FOR_QUOTA, reset wake, no paid fallback.
6. **OTO-6 — Brain continuation robustness:** proposal contract, malformed recovery, repeated-proposal suppression.
7. **OTO-7 — Steering + Assumptions + Micro-feedback:** mid-flight steering, authority-safe constraint update, assumption ledger, concise status feedback.
8. **OTO-8 — Streaming + Notification:** partial artifacts, panel flow, notification dedup.
9. **OTO-9 — Completion + Compaction + Otonom acceptance:** deterministic fast completion, conditional semantic verifier, privacy-preserving compact projection, exact acceptance.

### SERBEST

1. **SER-1 — SubGoal + Direct Child runtime:** flat depth=1 child model, result bridge, parent budget.
2. **SER-2 — Child lifecycle:** progress lease, active TTL, sleep/resume, stale fencing, parallel limit.
3. **SER-3 — Sibling orchestration:** sequential/parallel sibling delegation, cloud concurrency=1, mode downgrade/upgrade.
4. **SER-4 — PC/Core + Windows acceptance:** ComputerWorker gate, pause/cancel/stale result and real-PC acceptance.

## 34. Başlangıçta özellikle yapılmayacak karmaşıklıklar

- distributed agent cluster,
- multi-level delegation tree,
- 10 paralel child,
- karmaşık multi-PC migration,
- onlarca budget profili,
- sürekli quota polling,
- her read işlemine approval,
- blanket domain-level double-confirmation,
- ikinci scheduler/state/permission/completion authority.

## 35. Ürün karakteri

> **Mümkün olan işi kendi yap.**

> **Sonuç geldikçe kullanıcıya göster.**

> **Kullanıcı çalışırken yön değiştirebilsin.**

> **Güvenlik kontrolleri görünmez ve ucuz olsun; gereksiz sürtünme yaratmasın.**

> **Para, authority, özel veri çıkışı ve geri döndürülemez effect Core sınırını asla aşmasın.**

Bu v1.1 tasarımı uygulama başlamadan önce dondurulmuştur. Yeni fikirler otomatik olarak v1.1 scope'una girmez; backlog/kalite önerisi olarak değerlendirilir ve ancak gerçek kullanım gerekçesi varsa sonraki sürümde mimariyi değiştirir.
