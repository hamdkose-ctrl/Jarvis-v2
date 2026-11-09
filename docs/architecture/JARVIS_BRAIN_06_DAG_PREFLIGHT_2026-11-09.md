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
