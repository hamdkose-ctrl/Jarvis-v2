# BRAIN-06 DAG preflight — 9 Kasım 2026

**Durum:** Hazırlık denetimi; üretim davranışı değiştirilmedi.

**Ölçülen taban:** `origin/main` / `b6f192c56d73399fd6914c6f0e12b38edafc1507`.

Bu belge yeni bir yol haritası ya da ikinci sözleşme değildir. Uygulama sırası
`docs/Jarvis_Yol_Haritasi.md`'dir; BRAIN-06'nın mevcut kaynakla gerçek temasını,
sonraki dar uygulama paketinin sahiplik sınırlarını kaydeder.

## Karar

BRAIN-05'in çoklu GoalState/Goal Resolver kullanıcı akışı netleşmeden ortak
yürütücü değiştirilmeyecek. Bu nedenle bu preflight paketi `task_agents`,
`task_queue`, `goal_executor`, GoalState ya da Scheduler kodunu değiştirmez;
yeni store, scheduler, keyword splitter veya model çağrısı eklemez.

Model uzun hedef için yalnız plan/revizyon **proposal** eder. Core, hedef
kimliği ve sahibi, yaşam döngüsü, plan sürümü, capability/şema, bağımlılık,
izin/effect ve sonuç kabulünü doğrular. Bu ayrım,
`JARVIS_BRAIN_ARCHITECTURE_CONTRACT_V2.md` §7–11'in uygulanacak sözleşmesidir;
bu belge onu genişletmez.

## Güncel üretim envanteri

| Yüzey | Gerçekte yaptığı | BRAIN-06 için durumu |
| --- | --- | --- |
| `modules/task_agents.py` | Owner'a bağlı JSON job günlüğünde en çok sekiz, yalnız önceki kimliklere bağlı, doğrulanmış açık DAG'i yürütür. Tamamlanan dosya artifact'ini ve replay-safe resume'u denetler. | **Legacy/uyumluluk yürütücüsü.** `plan_version`, Core kabul edilen dinamik revizyon, node acceptance ve plan-fencing taşımaz. Yeni canonical plan sahibi değildir. |
| `modules/task_queue.py` | Opt-in, izinli worker kümesi için kalıcı kuyruk, job kimliği, heartbeat lease ve resume sağlar. | **Scheduler değildir.** Queue lease'i plan/GoalState gerçekliği veya worker-result fencing'i değildir; BRAIN-07'de mevcut runtime sözleşmesiyle tekleştirilecek. |
| `modules/goal_executor.py` | Typed Goal araç protokolünü yürütür. Modelin eski yalnız-`tasks` zarfını `legacy_plan` olarak doğrular, ardından `task_agents.execute()` çağırır ve sonucu compatibility adımlarına yansıtır. | **Eski sahip korunuyor.** BRAIN-06 bu girişe yeni ham niyet/regex yolu eklemeyecek ve onu BRAIN-05'ten önce değiştirmeyecek. |
| `modules/worker_result.py`, `modules/worker_result_commit.py` | Typed WorkerResult için goal/job sürümü, attempt, capability sürümü ve identity fencing'i doğrular; canonical GoalState commit'i CAS ile yapar. | **Yeniden kullanılacak Core kabul hattı.** BRAIN-06 plan sürümü/alt-görev kimliğini bu hattın yerine paralel bir sonuç deposu kurmadan bağlamalı. |
| `modules/goal_state_store.py` | Canonical GoalState için versioned CAS sağlar. | **Tek canonical state tabanı.** Plan ilişkileri burada mevcut şema/Reducer genişletilerek tutulmalı; ayrı task/plan truth store yasak. |

## Eksik bağlantılar ve sahipleri

| Gerekli BRAIN-06 bağ | Eksik olan | Doğru sahip / sonraki aşama |
| --- | --- | --- |
| Hedef seçimi ve kullanıcı steering'i | Birden çok aktif hedefte modelin önerdiği `target_goal_id` için üretim Goal Resolver akışı yok. | **BRAIN-05:** Brain proposal; Core owner/status/version doğrulaması. |
| Dinamik plan | Canonical GoalState'te `plan_version`, node graph, beklenen çıktı/acceptance ve doğrulanmış plan revizyonu için üretim reducer yolu yok. | **BRAIN-06:** Core/Reducer, BRAIN-05 kimliği üstünde. |
| Sonuç kabul/fencing | WorkerResult'ın `expected_job_version` fence'i var; plan sürümü ve task-node geçerliliğiyle ilişkilendirilmiş değil. | **BRAIN-06:** mevcut result-commit hattını daraltarak plan/node fence'i eklemek; worker başarı metni completion değildir. |
| Çalıştırılabilir işi seçme | `task_agents` statik planı sıra/dalga ile seçer; Core'un güncel planından dependency-ready node seçmez. | **BRAIN-06 + BRAIN-07 sınırı:** BRAIN-06 yalnız Core uygunluk/plan ilişkisi; lease, heartbeat, resource arbitration BRAIN-07. |
| Tamamlanmış kanıtın tekrar kullanımı | Legacy resume yalnız kayıtlı `done` output/artifact kontrolünü yapar; yeni revizyonda kanıtın hâlâ geçerli olup olmadığını Core kararıyla taşımıyor. | **BRAIN-06:** Core acceptance/reuse kararı; gerekirse yeni plan sürümü altında yeniden çalıştırma. |

## Uygulama sırası ve dar kesit

1. BRAIN-05, aktif Goal kimlik kartını ve steering operasyonlarını canonical
   GoalState üstünde bağlar. `goal_executor.latest()` yalnız compatibility / read
   gözlemi olarak kalır.
2. BRAIN-06'nın ilk kod paketi, mevcut canonical sözleşmeye minimum plan node
   ve `plan_version` reducer geçişini ekler. Planner yalnız uzun bağımlı hedefte
   proposal üretir; first-turn Understanding zarfına büyük DAG gömülmez.
3. Core, proposal'daki task/dependency/capability/input/expected-output/
   acceptance alanlarını kapalı şema ve Goal owner/version ile doğrular. Plan
   revizyonu CAS ile tek sürüm artırır.
4. Worker başlatmadan önce seçilmiş node ve plan sürümü fence edilir. Geç gelen
   sonuç aynı fence ile reddedilir; tamamlanan kanıt yalnız Core'un hâlâ geçerli
   bulması halinde yeniden kullanılır.
5. Legacy `legacy_plan → task_agents` yolu, yeni canonical akış gerçek üretim
   bağlantısı ve regresyonlarıyla doğrulanana kadar sahibi olarak kalır. Cutover
   sonrası yalnız duplicate semantic/plan authority kaldırılır; kanıtlanmış
   domain biçim ve exact protokoller gerekçesiz silinmez.

## Paralel çalışma sınırı

Bu preflight'ın ortak dosya noktaları `modules/goal_executor.py`,
`modules/goal_state_store.py`, `modules/worker_result*.py`,
`modules/task_agents.py` ve `modules/task_queue.py`dir. Bu pakette hiçbirine
değişiklik yoktur. Sonraki BRAIN-06 kod paketi bunları BRAIN-05 (Goal kimliği/
steering) ve BRAIN-07 (scheduler/lease) sahipleriyle dosya başına önceden
koordine etmelidir; başka bir ajanın dalı alınmaz.

## Kabul paketi için zorunlu regresyonlar

Son uygulama paketi, en az aşağıdakileri üretim bağlantısında sınamalıdır:

- sahip olmayan, stale veya belirsiz `goal_id` ile plan/revizyon reddi;
- revizyonda `plan_version` artışı ve eski sürüm WorkerResult'ın CAS/fence öncesi
  reddi;
- bağımlılığı tamamlanmamış node'un yürütülmemesi;
- bağımsız hazır node'ların scheduler sınırı içinde ayrık kalması;
- plan revizyonunda hâlâ geçerli doğrulanmış output'un tekrar yürütülmemesi;
- geçersizleşen output, unknown effect, approval veya capability şeması için
  fail-closed/reconcile davranışı;
- direct action ve action batch'in Planner/DAG'e zorlanmaması;
- `legacy_plan → task_agents` compatibility yolunun yeni canonical akış gelene
  kadar değişmeden kalması, cutover sonrasında ise ikinci plan authority
  olmaması.

Bu doküman canlı Brain Full veya watcher çalıştırma talimatı değildir. Kod
paketi hazır olduğunda odaklı testler ve tam `modules.validation` bir kez,
exact head üzerinde çalıştırılır; Windows CI/gerçek-PC kabulü ayrı kanıttır.

## 10 Kasım 2026 — BRAIN-06B yapısal node fence dilimi (ayrı PR)

BRAIN-05 merged ve BRAIN-06A'nın `goal_plan`/CAS şema çekirdeği main'dedir. Bu tarihli not orijinal 9 Kasım preflight kararlarını geriye dönük değiştirmez.

`modules/goal_plan_gate.py` yalnız canonical GoalState snapshot'ını okur: plan node/bağımlılık/acceptance/input dahil transitive fingerprint üretir. `NodeCandidate` owner/job, `GoalState.version`, `plan_version`, node ve capability'yi snapshot'a bağlar; `revalidate` geç gelen veya değişmiş seçimi efekt öncesi reddedebilir. `initial_roots` yalnız başlangıç adayıdır. `revision_reuse_candidates` aynı yapı/ata parmak izi olan node'ları listeler; bunlar **tamamlanan veya kabul edilmiş** node değildir. Önceki sonuç kanıtı geçerli mi sorusunu yalnız Core + WorkerResult verifier cevaplayabilir.

**Bu PR production runtime'a bağlı değildir.** Hiçbir iş dispatch edilmez veya yeni worker, lease, receipt, permission verilmez. Eski `task_agents`/Scheduler yürütme yolu değiştirilmez. Devamındaki BRAIN-06C, mevcut `worker_result_commit`/Core fence'ine plan/node sürümü bağlayacak; BRAIN-07 tek Scheduler üzerinden kaynak lease'i sağlayacak. O aşamada `NodeCandidate` bir izin/lease kanıtı sayılmayacak, her dispatch Core tarafından yeniden doğrulanacaktır.

## 10 Kasım 2026 — BRAIN-06C plan-bound WorkerResult (dar runtime dikişi)

`modules/runtime_worker_result.py` canonical planı bulunan durable yürütmede güncel GoalState snapshot'ından node/plan identity ve transitive fingerprint alır. Başlangıç için **yalnız dependency-free `read_only`** capability'ler içeri alınır; mevcut WorkerResult v1'in zorunlu şeması değiştirilmez, planlı denemelerde tam `worker_result.plan.v1` şeması seçilir. Eski v1 zarfı planlı GoalState'e commit edilemez. `worker_result_commit` mevcut GoalState CAS'inden önce tekrar plan sürümü ve node fingerprint kontrolünü yapar; revizyon/başka owner/yanlış capability/bozulmuş node veya eski GoalState sürümü fail-closed reddedilir.

BRAIN-06B `NodeCandidate` yalnız düğüm hazırlama yardımcısıdır; bu PR onu tek başına yetki ya da completion kanıtı saymaz. Bağımlı node'ların doğrulanmış input/çıktı delili, efekt/approval, paralel Scheduler'ın lease arbitration/fencing'i, plan revizyonunda güvenilir tamamlanan iş yeniden kullanım ve genel durum toplama **henüz yoktur**. İki bağımsız root'un aynı GoalState sürümünden paralel başlaması durumunda ikinci tamamlanma CAS reddine düşebilir; BRAIN-07 çözülmeden bunu paralellik kabulü diye sunmayın. `reconcile_worker_result` ve `effect_recovery_runtime` eski kimliklerle çalışmaya devam eder; planlı koşullu etkiler bu geçişte başlatılmaz. Gerçek Windows PC işitsel/worker/model doğrulaması bu pakette yapılmaz.

Bu değişiklik yalnız şu mevcut kanalları daraltır: `runtime_worker_result.prepare`, `worker_result_hook.wrap_output`, `worker_result.accept`, `worker_result_commit.commit` ve `reconcile_worker_result`. Yeni kayıt deposu, worker seçici, prompt, permission grant veya ikinci Scheduler kurulmadı. Exact-head CI + aynı SHA PC watcher tamamlanmadan BRAIN-06C dar dilimi bile merge edilmez.

BRAIN-06C recovery güvenlik notu: planlı bir adım için kabul edilmiş eski execution fence evidence'ı yoksa salt-okunur reconcile gözlemi, en güncel plan sürümüne aitmiş gibi yeni kimlikle yazılamaz. Normal yol, kanıtlı eski komutun aynı `plan_version` + `node_digest` ile idempotent yeniden okunmasıdır; farklı plan revizyonuna ait gözlem reddedilir. İlk commit'ten önceki kesinti yeni planda kendiliğinden başarıya çevrilmez (BRAIN-08 checkpoint/recovery'ye bırakılır).

## 10 Kasım 2026 — BRAIN-07A ResourceLease yapıtaşı

BRAIN-06C planlı WorkerResult fence exact-SHA CI ve PC watcher kabulü sonrası `main`e birleştirildi. BRAIN-07A, **ikinci Scheduler değildir**: `modules/resource_leases.py` yalnız bugünkü Scheduler sahibinin ileride çağırabileceği bellek içi `LeaseTable` sözleşmesini ekler. `pc_desktop` tek global exclusive kaynak; `window:<hwnd>`, `file:<sha256>`, `browser_session:<id>`, `gmail_account:<id>`, `provider:<id>` kanonik anahtarları atomik çoklu rezervasyonla yönetilir. `LeaseTicket` epoch, seri, renewal generation, owner/job/step/plan-version/command ve monotonic deadline taşır. Heartbeat eski token'ı çitleyerek yeniler; süre aşımı sonrası eski Worker release/validate işlemine izin verilmez. `tests/test_brain_07a_resource_leases.py` bunları sahte saat ve sahte işçilerle doğrular.

**Üretim sınırlaması:** Bu tabloda multi-process, disk kalıcılığı, restart sonrası lease recovery, Core permission, gerçek worker lifecycle veya effect öncesi/sonrası doğrulanmış fencing **yok**. Lease'i almak effect izni değildir. Bugünkü `task_queue`/legacy `task_agents` planlama otoritesi değişmedi; yeni executor açılmadı, paralel GörevState CAS yarışları çözülmedi. BRAIN-07B için mevcut Scheduler içinden tek sahiplik, cross-process/persistent lease, atomic fencing ve `worker_result_commit` sonucuna exact lease token dahil etme ayrı PR gerektirir. BRAIN-07A merge edilse dahi gerçek çoklu görev kabulü tamamlanmış sayılmaz.


## 10 Kasım 2026 — BRAIN-07B canonical read-only Lease admission (taslak)

BRAIN-07A in-process atomik `LeaseTable` exact-SHA Windows CI + aynı SHA PC watcher kabulünden sonra main'e eklendi. `modules/scheduler_resource_gate.py` yeni Scheduler değildir ve global `LeaseTable` yaratmaz: var olan Scheduler'ın ileride enjekte edeceği tablo üzerinde `goal_plan_gate.revalidate` ile canonical snapshot/owner/job/version/plan-node ve upstream fingerprint doğrular. Kullanılan capability metadata `capability_manifest.from_task_tool` / `from_goal_tool` kaynağından gelir; model resource/permission metninden karar verilmez.

Bilinçli ilk destek: salt-okunur, bağımsız node köklerinde `task.computer` ve `goal.observe` => tek global `pc_desktop`; `task.file` => diskte var olan dosyanın resolve edilmiş yolundan SHA-256 kilidi; `task.account` => owner-bazlı, servis bazlı kaynak kimliği. Aynı OAuth hesabının birden fazla owner/profilde kullanılıp kullanılmadığı henüz doğrulanmadığı için hesap kilidini gerçek dış hesap için global tekillik diye yorumlamayın. `task.research` gibi stateless okumalar uydurma global provider kilidi ile seri hale getirilmez; bu ilk admission yardımcısı onları henüz kapsamaz. `goal.document`, yazar, yayın, medya, tarayıcı efektleri, bilinmeyen capability, dependency kanıtı bulunmayan alt düğümler reddedilir.

`admit` yalnız bir LeaseTicket üretir; `validate_before_dispatch` aynı exact current lease, command attempt, owner/job/step/plan_version ve türetilmiş kaynakları tekrar doğrular. **Bu araç iş başlatmaz, effect izni vermez, Completion/WorkerResult kabulü yapmaz.** Mevcut `task_agents` / `task_queue` çalıştırıcı yollarına bağlanmadı. Etkili işler için ayrı Permission Gate, durable multi-process lease, worker cancellation, heartbeat lifecycle ve kabul edilen output ile exact ticket idempotency / fence gerekecek; o tarihe kadar eski çalıştırma yollarını güvenlik kanıtı olmadan silmeyin. `tests/test_brain_07b_scheduler_resource_gate.py` sahte scheduler/clock + gerçek geçici dosya ile koruyucu sözleşmeyi sınar; gerçek Windows kaynak çekişme kabulü değildir.
