# Brain / Core: tek uygulama kapsamı — 14 Kasım 2026

## Kapsam ve mevcut kaynak

Başlangıç main `7df1105` (#613/#617/#621/#622/#623/#624 birleşmiş). Bu belge kaynak davranışını ve kabul ölçütlerini tanımlar; kendi başına CI, gerçek model veya fiziksel cihaz PASS kaydı değildir. Canlı kanıt PR'ın exact kaynak SHA'sı üzerinden izlenir. #545 ve #584 geniş kabul sınırları korunur; bu PR onların tamamını otomatik kapatmaz.

Uygulama geliştirme aşamasındadır. Amaç eksik davranışı doğru katmanda tamamlamaktır; eski uygulama çalışsın diye ikinci parser, ikinci GoalState, ikinci Scheduler veya örtük yetki yolu eklemek değildir.

## Katman ve çağrı sözleşmesi

| Sahip | Yapılan iş |
|---|---|
| `brain_contracts.neutral_observation` | Üretim ve ölçüm için ortak, niyet seçmeyen başlangıç girdisi |
| `brain_entry.prepare` / model adapter | Owner-bound gözlem, State/Fast, tek anlamsal öneri; typed taşıyıcı |
| `core_brain_adapter` | Core map/ref doğrulaması, pending lifecycle, direct/batch handoff ve sonuç feedback'i |
| `canonical_goal_control` | Aynı owner/job/snapshot için checkpoint pause/resume, edit ve öncelik kontrolü |
| `canonical_plan_revision` | Mevcut task planner'dan revize read-only DAG önerisi; eski domain kanıtını kilit dışında yeniden doğrulama |
| `goal_state_compat` / reducer / CAS | Canonical lifecycle, intent, yeni plan ve doğrulanmış sonuç reuse kabulü |
| Mevcut `task_queue.start` | İlk plan, revizyon, hazır node ve completion için tek Scheduler / sınırlı worker havuzu |
| Domain/specialist/result adapter | Mevcut permission/effect/lease kapılarıyla iş; WorkerResult kanıtı |

`brain_entry.handoff/core_plan` çağrı uyumluluğunu koruyan ince girişlerdir. Yürütme kodu Core adapter'ındadır. `job_front.route`, `goal_executor._save`, `command_manager.engine_control` artık kendi çağrı noktalarında koruma/metadata uygular; global fonksiyon yeniden ataması yoktur. Eski `_install_*` yardımcıları yalnız izole eski test/çağrı uyumluluğu için etkisizdir; üretim korunmasını kurmazlar.

## Batch domain sonuçları

Not/görev ekleme, exact task complete, not update/delete ve doğrulanmış yerel tercih yazımları mevcut string arayüzünü koruyan `ActionOutcome` ile gerçek başarı/ret döndürür. Pending/onay Core'a aittir; yeni pending sonraki batch adımını durdurur. Domain başarılı olduğunda bağımlı adım açılır; handled routing tek başına başarı değildir.

Typed başarı kanıtı olmayan adapter çıktısı unknown kalır. Cevap metninden veya string'in dolu olmasından başarı çıkarılmaz. Örneğin medya tuşu tetikleme, gerçek oynatıcının şarkı değiştirdiğini kanıtlamaz. Batch'e izin verilmiş olmak dependency success garantisi değildir.

Save hatası not/görev belleğini geri alır. ID sayacında boşluk kalabilir; başarısız işlem sonraki save'de hayalet not/görev olarak yazılmaz. Model/ham komut fallback'i eklenmez.

## Canonical hedef kontrol geçişleri

| Durum / talep | Core ve Scheduler davranışı |
|---|---|
| Queued veya adım başlamamış hedefi beklet | Core paused + eşleşen ExecutionRecord; yeni admission yok |
| Adım/ilk planlama sürerken beklet | Core `PAUSE_REQUESTED`; yeni node başlamaz; admitted bounded adım kendi claim'iyle checkpoint'e ulaşır; sonra paused |
| Bekletme isteğinden vazgeçip devam et | Scheduling-only blocker geri çekilir; aynı çalışan adım invalid edilmez |
| Paused hedefe devam | Aynı job ve plan tekrar schedulable; done node tekrarlanmaz; legacy run açılmaz |
| Çalışan hedefi değiştir/alt iş ekle | Edit proposal mevcut journal'da checkpoint bekler; eski adımın sonucu doğrulanınca Core intent + revision queue |
| Güvenli durmuş hedefi değiştir/alt iş ekle | Core intent + paused; aynı Scheduler `revision_queued` işini alır |
| İlk plan öncesi açık düzeltme | Aynı job; Core değişikliğine bağlı yeni explicit planner generation; özgün request/owner kimliği korunur |
| Priority | Core `USER_GOAL_PRIORITY`; gerçek bounded offer sırası değişir; çalışan node'un planı invalid edilmez |
| İptal / eski kart / yanlış owner | Mevcut per-job Core sınırı; ilgisiz hedef değişmez; stale snapshot reddedilir |

Pause, başlamış HTTP çağrısının fiziksel olarak kesildiği iddiası değildir. Çalışan adımın sonunu beklediği kullanıcıya açıkça söylenir. Kanıtı belirsiz/failed started adım, resume ile ilk attempt'e sıfırlanmaz.

Scheduling-only audit istisnaları kapalı bir kümedir: `USER_GOAL_PRIORITY`, pause-request blocker ve onun açık geri çekilmesi. Gerçek pause/resume, semantic intent ve plan sürümü değişikliği eski in-flight attempt'i yeniden yetkilendirmez. Kalıcı çıktı okuması meşru pause/resume tarihçesi üzerinden yapılabilir; intent/plan drift'i görmezden gelmez.

## Yeni plan ve doğrulanmış reuse

1. Revizyon aynı `task_agents` task-graph önerisini kullanır. Destek hâlâ research/account/verify read-only kapsamıdır.
2. Yeni plan tam sonraki `plan_version` ile önerilir; Core identity/schema/input/dependency ve supported capability sınırlarını doğrular.
3. `revision_reuse_candidates` yalnız yapısal adaydır. Önceki planın gerçek Core audit prefix'i, accepted output digest'i ve domain verifier sonucu gerekir.
4. Domain doğrulaması Core lock dışında yapılır. Core kabulünde exact goal version, journal digest, plan digest ve eski output commitment tekrar karşılaştırılır.
5. Değişmiş parent kanıtı varsa child reuse edilmez. Eski unknown/started işi node ID değiştirerek yeniden yürütme yasaktır.
6. Core reuse kabulü mevcut evidence hattında, açık `reused_from` eski plan/command/output digest kaydıyla tutulur. Yeni harici worker çalıştırılmış gibi iddia edilmez; yeni planın tamamlanma kanıtı ancak bu kabulden sonra oluşur.
7. Eski plan/step/output geçmişi ExecutionRecord'da korunur. Kayıt boyutu güvenli sınırı aşıyorsa kabul başlamadan ret verilir.
8. Yeni projection, Core CAS'den önce mevcut journal'a hazırlanır. CAS sonrası kesintide yalnız exact kabul edilmiş projection tekrar yazılabilir; model veya provider tekrar çalıştırılmaz. Eşleşmeyen/tahrif edilmiş prepared projection fail-closed kalır.
9. Kullanıcı düzeltmeleri mevcut Core evidence/audit hattında sıralı `goal_intent_change` kayıtlarıdır; worker başarısı sayılmazlar. İlk planlama, revizyon ve son anlamsal tamamlanma aynı sıralı geçmişi görür. Böylece “A ekle → yalnız B olsun → C ekle” ile “yalnız B olsun → A ekle → C ekle” karışmaz. Eski kayıtlardaki aggregate intent korunur; geçmiş uydurulmaz. Yalnız ilk istek karşılandı diye yeni düzeltme/ek iş tamamlandı sayılmaz.

## Kaynak ve provider yaşam döngüsü

Mevcut havuz 4 global/3 aynı owner sınırını korur. Owner fairness, job cursor ve gerçek Core priority birlikte kullanılır. Sıra hint'i yetki değildir; seçilen offer ve priority diskten yeniden doğrulanır.

Worker deadline'ı geçip dış çağrı hâlâ dönmediyse, mevcut Scheduler denemeyi `CANONICAL_WORKER_DEADLINE_UNACCEPTED` + `quarantined` olarak kaydeder. Geç başarı kabul edilmez; aynı attempt tekrar sunulmaz. Canlı thread ve fiziksel claim dönmeden slot silinmez/yeni kopya açılmaz. Bu bounded karantina, provider thread'ini zorla öldürme veya dört hard-blocked thread varken yeni arka plan kapasitesi garantisi değildir.

Desteklenen adapter'larda mevcut HTTP/model/Google transport timeout ve request budget sınırları korunur. Kooperatif iptal fiziksel remote transaction iptali diye sunulmaz. Genel effectful reconcile ve trusted dış hesap subject'i bu uygulamayla icat edilmez.

## Native / IO kapsam matrisi

| Alan | Mevcut gerçek sınır | Bu uygulamadaki karar |
|---|---|---|
| Direct Core capability'ler | 68 kapalı schema/validator → Core intent → domain | Tam katalog ayrı ek tabloda; typed outcome olmayan sonuç unknown |
| Canonical research/account/verify | Manifest + runtime gate + scoped lease + WorkerResult + domain verify + CAS | Pause/priority overlap ve revision kabulü bu sınırları korur |
| Masaüstü/system/application | `desktop_agent._desktop_claim`, system_control ve mevcut PC protokolleri | İkinci desktop sahibi veya yeni izin yolu yok |
| Browser | `browser_agent._browser_claim`, mevcut permission/read-only gate | Browser canonical read-only DAG'a kendiliğinden eklenmez |
| Dosya düzenleme/undo | `files` receipt + gerçek source/destination `claim_paths` | Eski undo receipt ve no-clobber sınırı korunur |
| Belge/export/Excel | `conversion`, `workbench`: kaynak/hedef claim, staging + create-only publish | Dialog seçimi overwrite izni sayılmaz |
| Görsel/photo/math/upload | Mevcut create-only dosya publish + fiziksel claim | Eski #621/#622 kapsamı yeniden yazılmaz |
| Report/media/studio/PPTX | Mevcut worker pipeline file claims + evidence | Writer/media canonical read-only yetkisi kazanmaz |
| Study kaynak/catalog | Kaynak claim, catalog-before-destruction ve rollback | Katalog silme kanıtı ayrı domain'de kalır |
| History/finance/backup | Shared fiziksel claim; create-only backup; domain journal | Kabul edilmiş yollar korunur |
| Permission grants/reset | Mevcut cross-process claim ve kalıcı cutoff | Brain bu kayıtları yazan otorite olmaz |
| Queue/cron | SQLite claim/heartbeat; started unknown no replay | Yeni cron/queue motoru yok |
| Gmail/provider | Provider-wide OS-account claim; bounded Google transport | Trusted OAuth subject henüz genel garanti değil; BRAIN-08/Account |
| STT/TTS/LLM/output_device | #623 mevcut interactive claim + VoiceCoordinator | #625 ses işiyle çakışan ikinci değişiklik yok; fiziksel ses kabulü ayrı |
| Git/update/development/admin | Mevcut açık domain protokolü, izin/kilit ve kendi uygulama guard'ı | Yeni genel background effect yetkisi yok |
| Özel Profile/session/context | Mevcut owner/lock/storage sözleşmesi | Private metadata, fiziksel harici etkiyle aynı şey sayılmaz |

Bu tablo mevcut giriş kapsamının denetim kaydıdır; her üçüncü taraf uygulama, native SDK veya Windows cihazı için canlı fiziksel kabul iddiası değildir. Bağlantı kimliği ve genel harici effect reconciliation #584'ten sessizce düşürülmez.

## Kaldırılan kod ve korunanlar

Kaldırılan eski serbest cepheler: `tasks.handle/list_request`, `media.handle`, `outlook.handle`; kullanılmayan `agenda_read_request/agenda_open_request` grameri ve `_fix_word` facade/uygulaması. Testlerde ilgili gerçek domain işçileri ve typed Core yolu sınanır. Silinen gramer yerine yeni regex eklenmez.

Eski `understand` yalnız izole karakterizasyon/talimatsız fotoğraf gözlemi için kalır; production model ve canlı holdout'lar bunu niyet ön kararı olarak çağırmaz. `apply_model_understanding`, mevcut Core map, State/Fast/UI/makro/domain işçileri ve gerekli GoalState compatibility/migration korunur. Faz 0 yeniden açılmaz.

## Kabul ve sınırlar

`test_canonical_goal_steering.py` gerçek typed entry, geçici gerçek Profile/GoalState/ExecutionRecord, reducer/CAS ve gerçek tek Scheduler ile batch, pause/resume, checkpoint edit, plan version, reuse, priority, stale/unknown fence, projection crash ve deadline karantinasını sınar. Model/provider dış sınırı sentetiktir; canlı model doğruluğu veya insanın fiziksel cihaz kabulü değildir.

Gerekli son kapılar: ilgili regresyonlar, full validation, Architecture Guard, exact-source Windows CI ve aynı SHA PC watcher. Canlı Full/goal holdout, fiziksel Windows ve geniş Account/effectful kabul kanıtları ayrı kaydedilir. Ölçülmeyen şey passed diye yazılmaz; model rota/korpus/eşik değiştirilmez.
