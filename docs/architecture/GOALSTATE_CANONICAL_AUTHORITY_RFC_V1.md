# GoalState canonical authority RFC v1

Durum: **RFC — karar seçenekleri dokümanı**. Bu belge migration implementasyonu değildir, kod/test/workflow değiştirmez. `docs/architecture/GOALSTATE_CUTOVER_V1.md` (preflight sözleşmesi), `docs/architecture/JARVIS_GOALSTATE_CUTOVER_GAP_REGISTER_V1.md` (PR #303, kaynak-doğrulanmış gap register) ve `docs/architecture/GOALSTATE_CUTOVER_PREFLIGHT_V1.md` (PR #306, salt-okunur preflight aracı) içinde **CUTOVER BLOCKER** olarak işaretlenen dört kalemin her biri için somut karar seçenekleri, güvenlik/risk etkisi, önerilen karar, kabul kriteri, rollback sınırı ve gereken yeni testleri verir. Gerçek migration/cutover PR'ı bu RFC'nin kararlarını kaynak göstermeden ilerleyemez.

## Kapsam dışı (bilinçli olarak)

- `RuntimeEvent` production subscription — ayrı RFC/PR konusudur, gap register'da **DEFERRED** olarak işaretlenmiştir (`JARVIS_GOALSTATE_CUTOVER_GAP_REGISTER_V1.md` madde 38). Bu belge o kararı almaz ve bu belgeye gizlice sokulmamıştır.
- `ExecutionRecord` şeması/implementasyonu — `GOALSTATE_CUTOVER_V1.md` "Kilitli otorite sınırı" bölümünde ayrı sınır olarak tanımlanmıştır; `created`, `approval_at`, `goals/steps/outputs` gibi yürütme ayrıntıları gap register'da **DEFERRED** (madde 26, 27, 39) olarak işaretlidir. Bu RFC bu alanları canonical GoalState'e taşımaz, ExecutionRecord tasarımı önermez.
- `modules/goal_executor.py` yeniden yazımı, reducer/CAS otorite modeli değişikliği, worker/effect/permission değişikliği, CI/watcher değişikliği — tüm bunlar `GOALSTATE_CUTOVER_V1.md`'nin "Kapsam dışı" bölümünde zaten dışlanmıştır; bu RFC o sınırı değiştirmez.

## Zorunlu ilkeler (dört karar başlığının tamamına uygulanır)

Aşağıdaki ilkeler her seçenek değerlendirmesinde sabittir; bir seçenek bunlardan birini ihlal ediyorsa o seçenek reddedilir, "önerilen karar" olamaz:

1. **Dual authority yasak.** Herhangi bir anda tam olarak bir taraf (legacy JSON journal veya canonical GoalState) o job için lifecycle write authority'dir. İkisi aynı anda authority sayılamaz.
2. **Canonical authority olmadan legacy silinmez.** Legacy JSON dosyası, ilgili job için canonical GoalState authority olduğu açıkça kanıtlanmadan (identity eşleşmesi + lifecycle parity + rollback penceresi kapanmış) silinmez veya normalize edilmez.
3. **`done`/`cancelled` terminal.** Her iki tarafta da terminal state'ler yeniden açılamaz; authority geçişi veya reconcile süreci terminal state'i mutasyona uğratamaz.
4. **Worker/model/UI doğrudan GoalState yazamaz.** Tüm canonical mutasyonlar `core_state_reducer.apply` + CAS üzerinden, save-hook/compat katmanı aracılığıyla olur.
5. **Migration crash anında kör overwrite/retry yapamaz.** Migration/cutover sürecinde bir ara adım crash ederse, geri kalan adım "önceki durumu bilmeden" veya "sonucu doğrulamadan" tekrar denenemez; her adım idempotent ve kendi önkoşulunu (expected_version/expected identity) kanıtlamak zorundadır.

---

## Karar 1 — `execution_mode` otoriter mapping'i

> **KABUL EDİLDİ — 2026-10-25.** Yukarıdaki **Seçenek A** bu karar için resmen kabul edilmiştir: canonical `execution_mode` kalıcı olarak sabit `'agent'`dir; legacy job şemasında `fast`/`durable` karşılığı yoktur ve legacy payload'daki bir `execution_mode` alanı projection tarafından okunmaz. `modules/goal_state_compat.py::PROJECTION_EXECUTION_MODE` kabul edilmiş sabitin adıdır; davranış `tests/test_goal_state_persistence.py` (RFC Karar 1 bloğu) ile kilitlidir: legacy alan yoksa, farklı değer taşıyorsa veya yanlış tipteyse canonical projection yine `'agent'` üretir, persist edilmiş ve `advance()` edilmiş state identity'yi korur, `goal_state.EXECUTION_MODES` kümesine yeni değer eklenmez. Kaynak dal/PR: `gpt/goalstate-rfc-decision1-execution-mode` (`main` hedefli; kesin PR numarası ve merge SHA'sı GitHub'dadır). **Bu kabul yalnız Karar 1 içindir; Karar 2, 3 ve 4 hâlâ öneri aşamasındadır.**

**Bulgu (kaynak):** `modules/goal_state_compat.py::project` canonical `execution_mode` alanını doğrudan sabit `'agent'` olarak geçirir (satır 41). Legacy `goal_executor` job şemasında (`_REQUIRED = {'id','owner','request','state','goals','steps','outputs'}`, `modules/goal_state_save_hook.py`) `execution_mode` kavramı **hiç yoktur** — `modules/goal_executor.py` içinde bu alana dair hiçbir okuma/yazma bulunmuyor. `modules/goal_state.py::EXECUTION_MODES = {'fast','agent','durable'}` ve `execution_mode` canonical identity'nin immutable parçasıdır (`GOALSTATE_CUTOVER_V1.md` madde "Kilitli otorite sınırı" ve "Identity").

### Seçenekler

- **A. Sabit `'agent'` kalıcı kural olarak kabul edilir.** Legacy sistemde bugüne kadar üretilen tüm job'lar zaten agent-tipi yürütme olduğundan (fast/durable ayrımı legacy'de hiç mevcut değil), `'agent'` sabiti doğru ve yeterli kabul edilir; cutover sonrası da aynı kalır.
- **B. Legacy job şemasına yeni bir alan eklenip (`execution_mode` veya eşdeğeri) oradan türetilir.** `goal_executor.py` değişir — ama bu `GOALSTATE_CUTOVER_V1.md`'nin kapsam dışı maddesini ("`modules/goal_executor.py` değişikliği veya yeniden yazımı") ihlal eder.
- **C. Heuristic türetme** (örn. job'un belirli bir alanına veya worker tipine göre `fast`/`durable` tahmini). Identity alanı için tahmine dayalı mapping, dual authority ve identity collision riskini büyütür; `goal_state.py` identity'nin immutable ve net olmasını şart koşar.

### Güvenlik/risk etkisi

- A: Düşük risk — mevcut davranışı resmîleştirir, hiçbir kod değişikliği gerektirmez, identity collision riski yaratmaz.
- B: `goal_executor.py` değişikliği skope dışı olduğundan bu RFC seçeneği öneremez; yapılırsa ayrı RFC/PR gerekir.
- C: Yüksek risk — tahmine dayalı identity alanı, aynı legacy job için zaman içinde farklı `execution_mode` türetilmesine (identity drift) yol açabilir; CAS identity-mismatch reddi (`modules/goal_state_store.py::compare_and_swap`) bu durumda sürekli conflict üretebilir veya daha kötüsü, hatalı biçimde "farklı job" olarak kabul edilebilir.

### Önerilen karar

**A.** Legacy→canonical cutover kapsamında `execution_mode='agent'` sabiti otoriter mapping olarak kabul edilir. Gerekçe: legacy `goal_executor` şemasında `fast`/`durable` ayrımına karşılık gelen hiçbir alan yok; B ve C skope dışı değişiklik veya identity riski gerektiriyor. `fast`/`durable` modları şu an üretilmiyor; üretilmeye başlandığında (yeni bir worker tipi eklenirse) bu karar ayrı bir RFC ile yeniden açılır — bu RFC o günü öngörmez.

### Kabul kriteri

- Karar dokümante edilmiş ve `goal_state_compat.py::project` zaten bu sabiti uyguluyor (kod değişikliği gerekmez).
- Legacy şemada gerçekten `fast`/`durable`'a karşılık gelen hiçbir alan bulunmadığı kaynak kodla (grep/okuma) doğrulanmış olmalı (bu RFC'de doğrulandı: `modules/goal_executor.py` içinde `execution_mode` referansı yok).
- Cutover PR'ı bu kararı GOALSTATE_CUTOVER_V1.md Identity bölümüne referansla açıkça alıntılar.

### Rollback sınırı

- Bu karar salt bir **isimlendirme/sabit mapping** kararıdır, persistence veya authority değiştirmez; rollback'i authority rollback'inden ayrı değildir. Sabit `'agent'` kullanımı geri alınabilir değildir çünkü telafi edici bir "doğru" değer yoktur — ileride `fast`/`durable` eklenirse mevcut canonical kayıtlar `'agent'` olarak kalır (geçmişe dönük reclassification yapılmaz, bu reconcile politikası — Karar 4'e bakınız — için ayrı girdi olur).

### Gereken yeni testler

- `goal_state_compat.project()`'in her legacy state için her zaman `execution_mode == 'agent'` ürettiğini kilitleyen parity testi (mevcut testler bunu dolaylı doğruluyor olabilir ama execution_mode'a özel, açık bir regression testi gap register'da listelenmemiş).
- Legacy job şemasında `execution_mode`-benzeri bir alan varsa bile (ör. gelecekte eklenmişse) `project()`'in bunu okumadığını, sabit `'agent'` kullandığını kanıtlayan negatif test (drift koruması).

---

## Karar 2 — Legacy → canonical write authority'nin devredileceği atomik nokta

**KABUL EDİLDİ (kısmi — yalnız işaretleme, PR gpt/goalstate-authority-cutover-point):** Bu kararın "C" seçeneği, canonical GoalState'e eklenen opsiyonel `authority` alanıyla (job yaratılış/ilk `project()` anında `'canonical'`, önceden var olan kayıtlarda alan yokluğu = `'legacy'`) kodlandı. Bu PR SADECE bu işaretlemeyi ekler ve test eder; legacy JSON journal yazımının gerçekten durdurulması (authority'nin pratik sonucu) kapsam dışıdır ve ayrı, sonraki bir PR'a bırakılmıştır.

**Bulgu (kaynak):** `GOALSTATE_CUTOVER_V1.md`: "Mevcut runtime boyunca legacy `goal_executor` JSON journal **write authority** olarak kalır. Canonical GoalState bugün compatibility projection/sync katmanıdır." `modules/goal_state_save_hook.py::_atomic` sırası: `goal_state_compat.sync(job, canonical)` **önce**, `_ORIGINAL_ATOMIC(path, data)` (legacy write) **sonra**; sync hata verirse legacy write'a hiç ulaşılmaz (fail-closed, gap register madde "KAPALI" #1). Gap register madde 29: "Gerçek cutover, hangi atomik sınırda legacy authority'nin sona ereceğini açıkça tanımlamadan başlayamaz."

### Seçenekler

- **A. Per-job authority flip (bayraklı, dar).** Her job kendi canonical GoalState kaydında bir `authority` alanı taşımaz (bu, `goal_state.py` şemasını değiştirir — identity/lifecycle şemasına yeni alan eklemek demektir, GOALSTATE_CUTOVER_V1 "Legacy → canonical projection sınırı" ile gerilir); bunun yerine **save-hook seviyesinde, job id bazlı bir allowlist/registry** (canonical dosyanın yanında değil, ayrı bir migration-state dosyasında) hangi job'ların authority'si legacy'den canonical'a geçtiğini tutar. Bir job allowlist'teyse `_atomic`, legacy write'ı **atlar** (veya no-op/log-only yapar) ve tek authority canonical olur; registry'de değilse bugünkü davranış (legacy write authority, canonical sadece sync) sürer.
- **B. Global flip (tüm job'lar aynı anda).** Tek bir deploy/flag ile tüm job'lar için authority canonical'a geçer. `GOALSTATE_CUTOVER_V1.md`: "Big-bang migration yoktur." — bu seçenek doğrudan preflight sözleşmesini ihlal eder.
- **C. Yeni job'lar canonical-authority, var olan (in-flight) job'lar legacy-authority kalır, eski job'lar bitince (terminal olunca) registry'den düşer.** A'nın bir varyantı: flip noktası "job yaratılışı" olur, var olan job'lar dokunulmadan legacy authority'de tamamlanır.

### Güvenlik/risk etkisi

- A: Orta risk, kontrollü — "dar sınırdan" prensibiyle uyumlu (GOALSTATE_CUTOVER_V1 "İlk gerçek cutover açık, geri alınabilir ve dar bir sınırdan yapılır"). Risk: registry dosyasının kendisi bir CAS/atomicity sorunu taşımamalı; registry yazımı da fail-closed olmalı (registry güncellenmeden authority flip "etkiliymiş" gibi davranılmamalı).
- B: Yüksek risk — tüm job'lar aynı anda etkilenir, geri dönüşü yok denecek kadar geniş; preflight sözleşmesini (big-bang yasağı) doğrudan ihlal eder, **reddedilir**.
- C: A'ya benzer risk profili ama "hangi job authority'sinin hangi tarafta olduğu" belirsizliği daha az (yaratılış anında sabitlenir, runtime ortasında değişmez) — bu da race condition riskini A'dan daha düşük yapar.

### Önerilen karar

**C (A'nın dar bir varyantı):** Authority flip noktası **job yaratılış anı** olsun. Yeni açılan job'lar doğrudan canonical-authority olarak yaratılır (ilk `goal_state.new()` + `goal_state_store.create()` tek write authority olur, legacy JSON hiç yaratılmaz veya sadece read-only "izleme" kopyası olarak tutulur — bu ayrıntı implementasyon PR'ının kararıdır, bu RFC yalnızca "ne zaman" sorusuna karar verir). Var olan (cutover anında in-flight) job'lar terminal olana kadar legacy-authority kalır; registry gerekmez çünkü ayrım dosya varlığıyla (job cutover tarihinden önce mi sonra mı yaratıldı) doğal olarak yapılabilir. Gerekçe: "dar ve geri alınabilir" ilkesine en az ek mekanizma (yeni registry dosyası, yeni CAS yüzeyi) ile uyar; in-flight job'ların authority'si runtime ortasında değişmediği için Karar 4'teki (state/terminal mismatch) riskini azaltır.

### Kabul kriteri

- Cutover PR'ı "hangi job'lar legacy-authority, hangileri canonical-authority" sorusuna **tek, deterministik** bir kural göstermeli (örn. "job yaratılış timestamp'i cutover-flag aktivasyon anından önce/sonra" veya dosya sistemi düzeyinde ayrık bir işaret — implementasyon PR'ının kararı).
- Flip noktası **tek bir atomik yazma** ile belirlenmeli; "yarı geçmiş" bir job authority durumu asla gözlenmemeli (ilke 5: crash anında kör overwrite yasak).
- Var olan in-flight job'ların legacy-authority olarak **değişmeden** tamamlanabildiği kanıtlanmalı (regression: cutover sonrası eski job'larda legacy write hâlâ çalışıyor, canonical hâlâ sadece sync).

### Rollback sınırı

- Rollback, yalnızca **henüz hiçbir canonical-authority job terminal olmamışken** güvenlidir: flip noktasından sonra yaratılan ve halen aktif olan job'lar için "canonical authority" kararı geri alınıp yeniden legacy-authority'ye dönülebilir, çünkü henüz legacy tarafta hiç yazılmamış bir journal yok (bu da yeni bir boşluk yaratır — implementasyon PR'ı bu job'lar için legacy journal'ın geriye dönük nasıl oluşturulacağını tanımlamalı, bu RFC'nin kapsamı dışı, sadece sınırı işaretler).
- Zaten terminal olmuş canonical-authority job'lar için rollback yoktur — terminal state ilkesi (ilke 3) bunu zaten engeller.
- Legacy-authority kalan in-flight job'lar bu kararın rollback'inden hiç etkilenmez (zaten değişmemişler).

### Gereken yeni testler

- Cutover flip noktasından önce yaratılan bir job'un legacy-authority olarak kaldığını ve canonical'ın sadece sync/compatibility rolünde olduğunu kilitleyen regression testi.
- Flip noktasından sonra yaratılan bir job'un canonical-authority olduğunu (legacy write'ın hiç tetiklenmediğini veya read-only izleme kopyası olduğunu) doğrulayan test.
- Flip anında (job yaratılış sırasında) crash simülasyonu: canonical `create()` atomik tamamlanmadan süreç kesilirse job'un hiçbir authority'de "yarım" görünmediğini kanıtlayan test (ilke 5).

---

## Karar 3 — Missing-state / identity mismatch durumları

**Bulgu (kaynak):** `GOALSTATE_CUTOVER_V1.md` madde 3 "Missing state": legacy var/canonical yok, canonical var/legacy yok, identity mismatch, canonical dosya/şema geçersiz, legacy state projection tablosunda yok — bunlar ayrı ayrı tanımlanmadan cutover yoktur. Gap register madde 30 bunu **CUTOVER BLOCKER** işaretler. `GOALSTATE_CUTOVER_PREFLIGHT_V1.md` zaten bu durumları salt-okunur **reason_code** olarak tespit ediyor (`MISSING_CANONICAL`, `CANONICAL_CORRUPT`, `IDENTITY_MISMATCH`, `UNKNOWN_LEGACY_STATE`) ama **karar almıyor** — sadece raporluyor. Bugünkü `goal_state_compat.sync()`: canonical yoksa `project()`+`create()`; canonical varsa `load()`+`advance()`+CAS; identity mismatch'e özel bir dal yok (identity CAS seviyesinde `goal_state_store.compare_and_swap` tarafından reddedilir, ama bu "cutover authority" kararı değil, bugünkü compatibility sync davranışı).

### Seçenekler (her alt durum için)

**3a. Legacy var, canonical yok (preflight: `MISSING_CANONICAL`):**
- A. Otomatik `project()` ile canonical yaratılır (bugünkü `sync()` davranışı aynen cutover authority politikası sayılır).
- B. Cutover sürecinde bu durum **insan onayı gerektiren** bir ara duruma düşürülür (canonical otomatik yaratılmaz, migration aracı bunu "pending backfill" olarak işaretler).

**3b. Canonical var, legacy yok:**
- A. Canonical zaten authority ise (Karar 2'nin C seçeneğiyle: job cutover sonrası yaratıldıysa) bu **beklenen** durumdur, hata değildir.
- B. Canonical var ama job hâlâ legacy-authority döneminden kalmaysa (legacy dosya silinmiş/taşınmış) bu **anomali**dir — fail-closed raporlanır, otomatik silme/reset yapılmaz.

**3c. Identity mismatch (canonical `owner`/`job_id`/`goal` ≠ legacy `owner`/`id`/`request`):**
- A. Fail-closed: migration bu job'u atlar, insan incelemesi için raporlar, hiçbir taraf mutasyona uğratılmaz.
- B. "Son yazan kazanır" — otomatik olarak legacy'nin identity'si canonical'a yazılır. Bu, dual authority yasağı ve "kör overwrite yasak" ilkesini ihlal eder.

**3d. Canonical dosya/şema geçersiz (`CANONICAL_CORRUPT`):**
- A. Bugünkü `goal_state_store.py` davranışı (fail-closed, otomatik repair yok) cutover için de aynen kabul edilir.
- B. Otomatik silip yeniden `project()` ile oluşturulur — "kör overwrite" riski taşır, ilke 5'i ihlal eder.

**3e. Legacy state projection tablosunda yok (`UNKNOWN_LEGACY_STATE`):**
- A. Bugünkü davranış (fail-closed `ValueError`, sync kesilir, legacy write'a geçilmez) cutover için de aynen kabul edilir.

### Güvenlik/risk etkisi

- Her durumda "A" seçenekleri (fail-closed/mevcut davranışı resmîleştirme) düşük risk; "B" seçenekleri (otomatik backfill, son-yazan-kazanır, otomatik repair) ilke 2 ("canonical authority olmadan legacy silinmez") ve ilke 5'i (kör overwrite) ihlal eder ve **reddedilir**.
- 3a'da B seçeneği (insan onayı) risk açısından A'dan daha güvenli ama operasyonel sürtünme ekler; cutover'ın "dar ve kontrollü" ilkesiyle daha uyumlu.

### Önerilen karar

- 3a: **B** — legacy var/canonical yok durumu cutover sürecinde otomatik `project()`'e bırakılmaz; migration aracı bunu "backfill bekliyor" olarak işaretler, insan/operatör onayıyla tek-seferlik backfill yapılır (backfill de kendi CAS/create() atomicity'sini kullanır, kör overwrite yapmaz). Gerekçe: cutover öncesi mevcut `sync()` davranışı compatibility katmanı için yeterliydi ama "authority" kararı olarak otomatikleştirmek, ilke 5'teki "migration crash anında kör overwrite/retry yapamaz" gereksinimini backfill'in kendi başına taşımasını ister; operatör onayı ek bir doğrulama katmanı sağlar.
- 3b: **A** (beklenen) / **B** (anomali) — ikisi de fail-closed/raporlama ekseninde, otomatik aksiyon yok.
- 3c: **A** — fail-closed, insan incelemesi.
- 3d: **A** — bugünkü `goal_state_store.py` davranışı değişmeden kabul edilir.
- 3e: **A** — bugünkü davranış değişmeden kabul edilir.

Genel ilke: **hiçbir missing-state/mismatch durumu otomatik, insan onayı olmadan "karar" üretmez**; migration aracı (preflight checker'ın bir sonraki adımı) bu durumları sınıflandırır ama düzeltmez.

### Kabul kriteri

- Migration/cutover PR'ı, preflight checker'ın ürettiği her `reason_code` için yukarıdaki politikayı birebir uygulayan, kod kanıtlı bir davranış göstermeli (`MISSING_CANONICAL` → backfill-bekliyor işareti, otomatik `project()` yok; `IDENTITY_MISMATCH`/`CANONICAL_CORRUPT`/`UNKNOWN_LEGACY_STATE` → fail-closed, raporlanır, mutasyon yok).
- Hiçbir reason_code için "otomatik overwrite" veya "otomatik silme" davranışı eklenmemiş olmalı.

### Rollback sınırı

- 3a'daki tek-seferlik operatör-onaylı backfill, backfill tamamlanana kadar geri alınabilir (backfill henüz `create()` çağırmadıysa hiçbir şey değişmemiştir); backfill tamamlandıktan sonra job normal Karar 2/4 rollback kurallarına girer.
- 3b/3c/3d/3e için rollback kavramı yoktur çünkü önerilen karar hiçbir mutasyon yapmaz — "rollback sınırı" burada "hiçbir ileri hareket yapılmaz" ile eşdeğerdir.

### Gereken yeni testler

- Preflight checker'ın her reason_code'u için migration aracının (henüz yazılmamış) "aksiyon almama" davranışını kilitleyen test — yani `MISSING_CANONICAL` dışında hiçbir reason_code'un otomatik mutasyon tetiklemediğini kanıtlayan negatif testler.
- 3a backfill akışı için: operatör onayı olmadan backfill'in tetiklenmediğini, onayla tetiklendiğinde `create()`'in CAS/atomicity garantisini kullandığını doğrulayan test.
- Identity mismatch durumunda hem legacy hem canonical dosyanın **değişmeden** kaldığını (byte-level) doğrulayan test (preflight'ın kendi "dosya değişmez" testine benzer, `tests/test_goalstate_cutover_preflight.py::test_scan_does_not_modify_any_file` modeli).

---

## Karar 4 — Legacy/canonical state veya terminal uyuşmazlığında authority/reconcile politikası

**Bulgu (kaynak):** `modules/goal_state_compat.py::advance`: `if goal_state.terminal(current): return current` — canonical terminal ise legacy projection onu asla yeniden açmaz (gap register "KAPALI" madde, `test_terminal_canonical_state_is_not_reopened_by_legacy_projection` ile kilitli). Ancak bu sadece "terminal reopen engeli"dir; **hangi tarafın authority olacağı** ve **state divergence (terminal olmayan ama farklı state) durumunda ne yapılacağı** tanımlı değildir. `GOALSTATE_CUTOVER_V1.md` madde 2 "Terminal state": "İlk cutover, legacy ve canonical terminal uyuşmazlığında hangi tarafın otorite olacağını ve işlemin fail-closed mu, reconcile mı olacağını ayrıca tanımlamadan etkinleştirilemez." `GOALSTATE_CUTOVER_PREFLIGHT_V1.md` bu durumu `STATE_DIVERGENCE` ve `TERMINAL_DIVERGENCE` olarak ayrı raporluyor ama karar almıyor.

### Seçenekler

**4a. Terminal divergence** (canonical terminal, legacy hâlâ aktif — veya tersi, legacy terminal görünümlü ama canonical aktif):
- A. **Canonical authority kazanır, her zaman.** Canonical `done`/`cancelled` ise legacy'nin "hâlâ aktif" görünümü yok sayılır — zaten bugünkü `advance()` davranışı budur. Legacy tarafın kendisi (job yaratıcısı worker/executor) ayrıca "bu job zaten bitmiş" sinyalini alacak şekilde cutover implementasyonu ayarlanmalı (bu RFC'nin kapsamı dışı, implementasyon detayı).
- B. Fail-closed: terminal divergence tespit edildiğinde migration/cutover süreci o job için **durur**, insan incelemesi ister, hiçbir taraf otomatik authority kazanmaz.

**4b. State divergence (terminal olmayan, ör. legacy `running`, canonical `paused`):**
- A. Authority taraf (Karar 2'nin belirlediği taraf — flip noktasından önce legacy, sonra canonical) kazanır; diğer taraf sync/advance ile "takip eder" (bugünkü compatibility `advance()` davranışı, legacy-authority dönemi için).
- B. Her state divergence'ı insan onayı gerektiren bir duruma düşürür (4a-B gibi) — ama bu, normal/beklenen her sync() çağrısını (legacy state değiştiğinde canonical'ın "takip etmesi" zaten normaldir) yanlışlıkla blocker'a çevirebilir; bugünkü sistemde state divergence zaten rutin ve beklenen bir geçiş anıdır (job `running`'den `paused`'a geçtiğinde canonical henüz güncellenmemiş olabilir, sync bunu düzeltir).

### Güvenlik/risk etkisi

- 4a-A: Düşük risk — terminal state'in bozulmazlığını (ilke 3) korur, zaten mevcut `advance()` davranışının resmîleştirilmesi; ek risk yalnızca legacy tarafın "ben hâlâ çalışıyorum" zannederek iş üretmeye devam etmesi — bu implementasyon PR'ının (worker'ın terminal canonical'ı nasıl öğreneceği) sorumluluğu, bu RFC'nin kapsamı dışı ama **açıkça not edilmelidir**.
- 4a-B: Orta risk — daha güvenli ama "zaten kapalı" bir job için gereksiz operasyonel sürtünme; pratik değeri düşük çünkü ilke 3 zaten terminal'i koruyor.
- 4b-A: Düşük risk, bugünkü sistemle aynı — **önerilir**.
- 4b-B: Rutin geçişleri blocker'a çevirir, operasyonel olarak kullanılamaz hale getirir, **reddedilir**.

### Önerilen karar

- 4a: **A** — canonical terminal ise her zaman authority kazanır (bugünkü `advance()` davranışının cutover authority politikası olarak resmîleştirilmesi); ek olarak cutover implementasyon PR'ı legacy tarafın (worker/executor) terminal canonical'dan nasıl haberdar olacağını **ayrıca** tanımlamalı — bu RFC bu ayrıntıyı önermez, sadece zorunlu kılar.
- 4b: **A** — authority taraf (Karar 2 ile belirlenen) kazanır, diğer taraf onu "takip eder"; bu bugünkü compatibility `advance()` mantığının devamıdır, yeni bir reconcile mekanizması gerektirmez.

### Kabul kriteri

- Terminal divergence'ta hangi tarafın her zaman kazandığı (canonical) kod ve testle kanıtlanmalı; bu zaten `test_terminal_canonical_state_is_not_reopened_by_legacy_projection` ile kısmen kanıtlı — cutover PR'ı bunu "authority politikası" olarak açıkça adlandırmalı, yeni davranış eklemeden.
- State divergence'ta authority-taraf kazanır kuralı, Karar 2'nin flip-noktası tanımıyla birlikte test edilmeli: flip öncesi job'larda legacy kazanır (canonical sync ile takip eder), flip sonrası job'larda canonical kazanır (bu RFC kapsamında implementasyonu olmayan, ama kuralı bu belgede sabitlenen bir gereksinim).
- Legacy tarafın terminal canonical'ı öğrenme mekanizması cutover implementasyon PR'ında **ayrıca** belgelenmeli; bu RFC'nin kabul kriteri değildir ama bu RFC'nin kabulü, implementasyon PR'ının bu boşluğu doldurmasını şart koşar.

### Rollback sınırı

- 4a: Terminal state zaten rollback edilemez (ilke 3) — bu kararın "rollback sınırı" terminal state'in kendisidir, geri dönüş yoktur.
- 4b: State divergence reconcile'ı, authority-taraf henüz terminal olmadığı sürece geri alınabilir (authority taraf Karar 2 rollback kurallarına tabi); authority taraf terminal olduysa 4a'nın rollback-yok kuralı geçerli olur.

### Gereken yeni testler

- Terminal divergence senaryosu: canonical `done`, legacy hâlâ `running`/`approval` iken `sync()` çağrıldığında canonical'ın değişmediğini (mevcut testle örtüşüyor ama "authority politikası" çerçevesinde yeniden adlandırılmış, açık bir regression testi) doğrulayan test.
- Ters terminal divergence: legacy state'i `done`'a eşlenen bir değere sahipken canonical hâlâ aktifse (örn. canonical henüz sync edilmemiş ara durum), `sync()`'in canonical'ı doğru şekilde terminal'e taşıdığını (normal ileri geçiş, divergence değil) ayırt eden test — bu, "terminal divergence" ile "normal ileri senkronizasyon"un karıştırılmadığını kanıtlar.
- Flip-noktası öncesi/sonrası job'lar için state divergence reconcile yönünün (hangi taraf kazanıyor) Karar 2 ile tutarlı olduğunu kanıtlayan entegrasyon testi (Karar 2 implementasyonu yazıldığında eklenir; bu RFC şimdilik test gereksinimini kaydeder).

---

## Özet tablo

| # | Karar başlığı | Önerilen karar (tek cümle) |
|---|---|---|
| 1 | `execution_mode` otoriter mapping | Sabit `'agent'` kalıcı kural olarak kabul edilir; legacy şemada `fast`/`durable` karşılığı hiç yok. |
| 2 | Legacy→canonical authority geçiş noktası | Flip noktası job yaratılış anıdır: yeni job'lar doğrudan canonical-authority, var olan in-flight job'lar terminal olana kadar legacy-authority kalır; big-bang flip reddedilir. |
| 3 | Missing-state / identity mismatch | Her durumda fail-closed ve raporlama; otomatik backfill/silme/repair yok, `MISSING_CANONICAL` için tek-seferlik operatör-onaylı backfill istisnadır. |
| 4 | State/terminal uyuşmazlığı authority/reconcile | Terminal divergence'ta canonical her zaman kazanır (reopen yok); state divergence'ta Karar 2'nin belirlediği authority taraf kazanır, diğeri onu takip eder. |

## Kaynaklar

- `docs/architecture/GOALSTATE_CUTOVER_V1.md`
- `docs/architecture/JARVIS_GOALSTATE_CUTOVER_GAP_REGISTER_V1.md` (PR #303)
- `docs/architecture/GOALSTATE_CUTOVER_PREFLIGHT_V1.md` (PR #306)
- `modules/goal_state.py`
- `modules/goal_state_compat.py`
- `modules/goal_state_save_hook.py`
- `modules/core_state_reducer.py`
- `modules/goal_executor.py`
