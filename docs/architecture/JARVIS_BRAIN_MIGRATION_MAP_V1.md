# JARVIS BRAIN MIGRATION MAP V1

**Durum:** canonical migration denetimi — production davranışı değiştirmez.  
**İlk denetim kaynağı:** `origin/main` @ `344c1c7cc5290f63753908d1b7fe8b3d48c5a521`  
**Düzeltme tabanı:** `origin/main` @ `7c2d08913e53c0695df73eed0cff5e622ded56d3`  
**Hedef:** tek genel Jarvis Brain; agents/workers uzman yürütücüler.  
**Canonical referans:** `modules/brain_contracts.py`; migration map yeni zorunlu `UnderstandingResult` alanı icat etmez.

## 1. Canonical hedef ve karar kuralı

```text
USER
 ↓
EXACT STATE GATE
 ↓
DETERMINISTIC FAST GATE
 ↓
ACTIVE CONTEXT
 ↓
CANDIDATE BUILDER
 ↓
UNDERSTANDING / REFERENCE RESOLVER
 ↓
SEMANTIC INVARIANTS
 ↓
CONFIDENCE / AMBIGUITY
 ↓
UNDERSTANDING RESULT
 ↓
CORE
 ↓
AGENTS / WORKERS
```

Bu haritanın ana ayrımı şudur: Brain semantic understanding/proposal **responsibility/ownership** taşır; **authority taşımaz**. Brain canonical sözleşmedeki `capability_hint`, typed `arguments`, bounded `references`, `conversation_relation`, `temporal_need`, clarification/context proposal alanlarını üretir. Capability/action validation-selection, permission, effect, execution, completion ve final dispatch authority **Core'dadır**; Core hint'i canonical manifest/domain invariant ile doğrular, gerçek capability/action mapping'ini seçer ve dispatch eder. Gerçek kayıt/evidence/safety doğrulaması **domain invariantlarında**, işin yapılması **worker/domain execution'da** kalır. Regex tek başına kötü sayılmamıştır; yalnız fast-gate için exact/bounded grammar, düşük false-positive, açık target/state, cross-domain seçim yapmama, determinism ve reference inference yapmama şartlarının altısı birlikte aranmıştır.

**State Gate kuralı:** `State exists` ≠ `next utterance must be consumed`. Exact State Gate yalnız kesin bounded runtime protocol, explicit confirmation/denial, bounded candidate selection veya deterministic exact continuation olduğunda mesaj tüketebilir. Açık uçlu cevaplarda yeni utterance'ın pending soruya cevap mı (`ANSWER_TO_PENDING`), correction mı, topic change mi yoksa yeni request mi olduğu canonical `conversation_relation` + Understanding ile belirlenir. Watcher operational pending, weather location pending, Hoca açık uçlu kontrol cevabı, generic clarification, phone-photo açık uçlu follow-up ve WhatsApp `to`/`text` alan tamamlama “pending var, her mesajı yakala” kuralına dönmemelidir; domain-owned state ActiveContext'te görülebilir ama state varlığı tek başına consume authority değildir.

Denetim sonucu: **91 migration bulgusu**. KEEP=34, MOVE=42, RETIRE=13, NEEDS_DECISION=2.

## 2. Migration bulguları

| ID | Mevcut dosya/fonksiyon | Bugünkü rol | Caller | Sorun | Hedef sınıf | Hedef Brain parçası | Geçiş koşulu | Silme koşulu | Korunacak test/invariant |
|---|---|---|---|---|---|---|---|---|---|
| BRAIN-MIG-001 | engine_commands.py:handle → command_manager.engine_control | Jarvis kapat/uyku/uyan exact grammar | engine_commands.handle | Bounded protocol/control; domain seçmiyor | KEEP_FAST_GATE | DETERMINISTIC FAST GATE | Brain entry öncesi exact grammar listesi sabitlenir | Silinmez; yalnız ortak gate'e taşınabilir | engine control/source safety testleri |
| BRAIN-MIG-002 | job_front.py:wants/route | Çıplak devam/iptal ile açık task job seçimi | engine_commands.handle | Exact söz + gerçek open-state; eski task/goal ayrımını köprüler | KEEP_STATE_GATE | EXACT STATE GATE | GoalState/task state read-only görünümü sağlanır | Legacy task engine kalkarsa köprü sadeleşir | owner/open/stale/pending precedence |
| BRAIN-MIG-003 | goal_executor.py:handle + RESUME_COMMANDS | Hedef resume/approval/cancel protokolü | engine_commands.handle | Gerçek durable GoalState kontrolü; doğal intent değil | KEEP_STATE_GATE | EXACT STATE GATE | Canonical Brain pending/control envelope GoalState'i okuyabilmeli | Goal protocol aynı kalır; wrapper gerekmezse kaldırılır | stale job, approval, owner, cancel |
| BRAIN-MIG-004 | command_manager.py:awaiting_input/PENDING_INPUT_FIELDS | Session pending protokollerinin varlığını toplu görme | engine_commands.handle; job_front.route | State inventory faydalı; fakat pending varlığı açık uçlu utterance'ı otomatik consume etmemeli | KEEP_STATE_GATE | EXACT STATE GATE inventory | Alanlar typed PendingState görünümüne normalize edilir; yalnız exact/bounded protokoller gate tarafından tüketilir | Ham alan listesi yalnız tüm callerlara geçişten sonra kaldırılır | pending precedence; no broad consume |
| BRAIN-MIG-005 | app_actions.py:continue_voice confirmation branch | App action onayının owner+90s expiry ile tüketilmesi | command_manager.dispatch | Gerçek bekleyen onay; approval inference yapmıyor | KEEP_STATE_GATE | EXACT STATE GATE | PendingAction typed view Brain'e read-only sunulur | Legacy session shape kalkınca adapter silinir | owner/expiry/negative/positive token |
| BRAIN-MIG-006 | command_execution.py:pending_app/continue_app | Uygulama adayından sayı/ad ile seçim; 120s TTL | engine_commands.handle | Bounded candidate selection; farklı istek eski seçimi iptal ediyor | KEEP_STATE_GATE | EXACT STATE GATE | CandidateSelection state canonical gate'e görünür olur | Session adapter sonrası eski pocket silinir | TTL, exact candidate, no accidental approval |
| BRAIN-MIG-007 | engine_commands.py:_pending_photo branch | Telefondan fotoğraf geldiğinde 600s artifact follow-up state'i; exact cancel + geniş `_PHOTO_INTENT` serbest soru yolu | engine_commands.handle | Pending artifact gerçek; ancak `_PHOTO_INTENT` `bu/bunu/soru/bak/...` gibi geniş metni semantic photo follow-up sayıyor, eşleşmeyen utterance topic change olabiliyor; bütün akış Exact State Gate değildir | MOVE_TO_ACTIVE_CONTEXT | ACTIVE CONTEXT / UNDERSTANDING relation / REFERENCE RESOLVER | Pending photo metadata read-only ActiveContext'te ve artifact bounded candidate olarak görünür; exact cancel tokenları bounded State/Fast Gate olabilir; açık uçlu photo follow-up relation + semantic interpretation Understanding'de çözülür | Canonical artifact relation/resolver devredeyken broad `_PHOTO_INTENT` interception kaldırılır; exact cancel protokolü kalabilir | TTL, cancel, owner, no unrelated consume, artifact identity |
| BRAIN-MIG-008 | engine_commands.py:pending_organize branch | Klasör düzenleme onayı | engine_commands.handle | Gerçek pending effect confirmation | KEEP_STATE_GATE | EXACT STATE GATE | Canonical PendingEffect/permission hattına bağlanır | Legacy session confirmation wrapper sonrası | no mutation before approval |
| BRAIN-MIG-009 | engine_commands.py:pending_msg/_message_step | WhatsApp eksik `to`/`text` alanları + final confirm protokolü | engine_commands.handle | `stage=to` ve `stage=text` gelen herhangi bir command'ı alan değeri olarak yazabiliyor; yalnız `stage=confirm` bounded approval/denial. Bütün protokol Exact State Gate değildir | MOVE_TO_ACTIVE_CONTEXT | ACTIVE CONTEXT / UNDERSTANDING relation + exact confirm State Gate | `to`/`text` pending metadata read-only görünür; yeni utterance'ın gerçekten eksik alana cevap olup olmadığı `conversation_relation` + Understanding ile belirlenir ve unrelated request consume edilmez. `confirm` aşaması exact bounded approval/denial olarak State Gate'te kalabilir; permission/effect authority Core'da kalır | Canonical relation + messaging input adapter devredeyken broad `to`/`text` auto-consume kaldırılır; exact confirm protokolü korunabilir | recipient/message identity, no unrelated consume, exact approval/denial, no send without Core permission/effect |
| BRAIN-MIG-010 | engine_commands.py:pending_confirm | Shutdown/close-app bekleyen onayı | engine_commands.handle; engine_intents.dispatch | Gerçek effect confirmation; iki producer var | KEEP_STATE_GATE | EXACT STATE GATE | Tek PendingEffect view | Producerlar Brain understanding'e taşınınca legacy field adapter silinir | no effect without confirmation |
| BRAIN-MIG-011 | engine_commands.py:pending_level | '70' sonrası ses/parlaklık seçimi | engine_commands.handle | Bounded iki adaylı clarification state | KEEP_STATE_GATE | EXACT STATE GATE | CandidateSelection{volume,brightness} olarak görünür | Brain canonical clarification aynı state'i ürettiğinde | number bound, explicit target |
| BRAIN-MIG-012 | engine_commands.py:pending_weather_location | Hava için şehir cevabı bekleme | engine_commands.handle; engine_tools._weather | Pending state gerçek, fakat legacy kod iptal/boş dışındaki herhangi bir sonraki mesajı şehir cevabı sayabiliyor | MOVE_TO_ACTIVE_CONTEXT | ACTIVE CONTEXT / UNDERSTANDING relation | Pending weather state read-only görünür; yeni utterance'ın `ANSWER_TO_PENDING` olup olmadığı Understanding tarafından belirlenir | Canonical relation/slot resume devredeyken broad-consumption branch silinir | cancel/no empty city/no unrelated consume |
| BRAIN-MIG-013 | visual_chat.py:pending_visual | Görsel kaynağı sohbet/dosya seçimi | command_manager.dispatch | Bounded iki seçenekli pending state | KEEP_STATE_GATE | EXACT STATE GATE | Pending source selection typed view | Brain aynı seçim state'ini ürettiğinde | only sohbet/dosya; no accidental consume |
| BRAIN-MIG-014 | learning.py:pending_facts | Onay bekleyen hafıza adayları | learning.handle; live prompt/app_actions | Durable approval state, memory truth değil; explicit kaydet/kaydetme/numaralı seçim komutlarıyla tüketiliyor, unrelated metni sırf pending var diye yakalamıyor | KEEP_STATE_GATE | EXACT STATE GATE | Brain yalnız read-only pending-memory status görür; yalnız explicit bounded approval/rejection komutları gate olabilir | Silinmez; storage domain-owned kalır | unapproved facts not memory; no unrelated consume |
| BRAIN-MIG-015 | hoca.py:lesson.pending | Bekleyen açık uçlu kontrol sorusu | hoca.check_question/grade | Domain state gerçek; fakat pending varlığı her yeni mesajı cevap sayma authority'si vermemeli | MOVE_TO_ACTIVE_CONTEXT | ACTIVE CONTEXT / UNDERSTANDING relation | Hoca pending question read-only görünür; `ANSWER_TO_PENDING` relation canonical Understanding tarafından önerilir | Domain state kalır; broad interception varsa relation cutover sonrası kaldırılır | pending question correctness/no unrelated consume |
| BRAIN-MIG-016 | watcher.py:_PENDING/run_pending | Saatlik kota nedeniyle bekleyen background dosyalar | watcher.tick/handle | Operational quota/background state; genel kullanıcı mesajlarını consume eden pending protocol değildir | MOVE_TO_ACTIVE_CONTEXT | ACTIVE CONTEXT / watcher status source | Watcher/domain-owned state korunur; Brain'e gerektiğinde read-only pending count/status görünümü verilir | Silinmez; watcher state domain-owned kalır ve unrelated mesajları tüketmez | hourly cap/no duplicate/no unrelated consume |
| BRAIN-MIG-017 | engine_commands.py:_split_steps/_run_steps | 'önce/sonra/ardından' multi-step parser | engine_commands.handle | Global sequence understanding Brain'den önce yapılıyor | MOVE_TO_UNDERSTANDING | UNDERSTANDING | Ordering semantics canonical `arguments`/`reason_codes` veya request/input envelope üzerinden taşınır; migration map yeni zorunlu field tanımlamaz | Yeni Brain sequence acceptance geçince legacy parser kaldırılır | order, pending/effect boundaries |
| BRAIN-MIG-018 | router.py:classify | Genel intent/domain/clarify/task kararı | engine_tools.route → engine_commands.handle | İkinci genel beyin; context+catalog+LLM+regex bir arada | MOVE_TO_UNDERSTANDING | UNDERSTANDING / CONFIDENCE | Brain contracts + parity corpus + fallback hazır | Tüm callers UnderstandingResult kullanınca router classifier emekli | routing corpus/product outcomes |
| BRAIN-MIG-019 | work_modes.py:classify/action_request | chat/do/spec üst seviye semantik karar | router.classify | Cross-domain doğal dil kararı; fast-gate şartlarını sağlamıyor | MOVE_TO_UNDERSTANDING | UNDERSTANDING | Canonical `request_kind`, `conversation_relation`, `capability_hint` ve confidence semantics aynı ayrımı ifade eder; exact representation PR5'te contracta göre belirlenir | router legacy guard kalkınca | question vs execution |
| BRAIN-MIG-020 | freshness.py:fresh_request | Güncel dış veri ihtiyacı | router.classify; work_modes | Temporal ihtiyaç semantik; konu regex'i global intent seçiyor | MOVE_TO_UNDERSTANDING | UNDERSTANDING | Canonical `UnderstandingResult.temporal_need` kullanılır: STATIC / CURRENT / RECENT / HISTORICAL / UNSURE | İki caller canonical `temporal_need` sonucuna geçince | static/current/recent/historical/unsure regression |
| BRAIN-MIG-021 | router.py:_definition_question/_open_only_request fast branches | Tanım ve open-only semantik shortcut | router.classify | Bounded görünse de cross-domain user outcome seçiyor | MOVE_TO_UNDERSTANDING | UNDERSTANDING | Brain confidence ile aynı semantic outcome proposal'ını üretir | Router classifier cutover | definition/action regressions |
| BRAIN-MIG-022 | router.py → app_actions.reference_context | Komuta göre task/not/event/fact/rule/source kayıtlarını prompta toplar | router.classify | Global singleton profile + lexical candidate retrieval | MOVE_TO_CANDIDATE_BUILDER | CANDIDATE BUILDER | Owner-scoped providerlar candidate API verir | Brain candidate builder canlı olduğunda helper kaldırılır | owner isolation/no secret exposure |
| BRAIN-MIG-023 | engine_tools.py:route context assembly | recent_turns + last_command + pending_request JSON context | engine_commands.handle → runtime.route | Active context parçaları ad-hoc prompt stringi olarak birleşiyor | MOVE_TO_ACTIVE_CONTEXT | ACTIVE CONTEXT | Typed ActiveContext snapshot üretilecek | Router prompt context kaldırılınca | redaction/owner isolation |
| BRAIN-MIG-024 | session_state.py:SessionStore | Owner-scoped RAM conversation/pending state | engine_commands, command_manager, visual, app_actions | Doğru state sahibi; Brain ikinci kopya oluşturmamalı | MOVE_TO_ACTIVE_CONTEXT | ACTIVE CONTEXT | Read-only ActiveContext adapter SessionStore'dan okur | Store silinmez; yalnız tüketim adapteri değişir | owner ContextVar isolation |
| BRAIN-MIG-025 | session_state.py:last_command | Son başarılı routed komut | engine_tools.route | Referans sinyali ad-hoc ve TTL'siz; source timestamp taşımıyor | MOVE_TO_ACTIVE_CONTEXT | ACTIVE CONTEXT | Yalnız gerçek field/text provenance'a alınır; timestamp yoksa age üretilmez ve recency `UNSURE` kalır | Legacy field caller kalmayınca | owner/reset/no invented age |
| BRAIN-MIG-026 | session_state.py:pending_request | Clarify soru+orijinal komut pocket'ı | engine_intents.dispatch; engine_tools.route | Gerçek clarification continuation ama generic dict; canonical timestamp/expiry yok ve açık uçlu cevap relation gerektiriyor | MOVE_TO_ACTIVE_CONTEXT | ACTIVE CONTEXT / UNDERSTANDING relation | Gerçek source alanları read-only görünür; source'ta olmayan expiry/TTL icat edilmez; `ANSWER_TO_PENDING` relation Understanding tarafından belirlenir | Canonical pending clarification sonrası | never infer approval/no invented TTL/no unrelated consume |
| BRAIN-MIG-027 | chat_translation.py:resolve | 'bunu/son cevabı/önceki metni çevir' kaynak çözümü | command_manager.dispatch | Kendi **legacy consumer** 2 saatlik history resolver'ı; genel referans sistemiyle yarışıyor | MOVE_TO_REFERENCE_RESOLVER | REFERENCE RESOLVER | Brain resolver candidate/provenance ile translation source döndürür; canonical history için global 2h TTL tanımlanmaz | Translation canonical resolver kullanınca | latest original user text; reset boundary; legacy 2h parity where required |
| BRAIN-MIG-028 | chat_translation.py:_sources | RAM son çeviri kaynağı cache'i | chat_translation.remember/resolve | İkinci kısa süreli truth pocket; history ile fallback yarışıyor | RETIRE_AFTER_CUTOVER | ACTIVE CONTEXT | History/session source provenance yeterli olmalı | Resolver parity sonrası `_sources` kaldırılır | reset/no stale source |
| BRAIN-MIG-029 | chat_translation.py:_resets/chat_sessions.json | Yeni sohbet sonrası history kesme sınırı | chat_translation.recent; engine_voice._recent_turns | Durable session boundary; ikinci semantic memory olmamalı | MOVE_TO_ACTIVE_CONTEXT | ACTIVE CONTEXT | Conversation epoch/read-only boundary view | Domain storage kalabilir; consumers adaptere geçer | no pre-reset reference |
| BRAIN-MIG-030 | main_documents.py:_resolve_doc candidate enumeration | İzinli dosyalarda exact/stem aday toplama | engine_intents doc_*; engine_tools delegate | Candidate retrieval ve referans seçimi aynı fonksiyonda | MOVE_TO_CANDIDATE_BUILDER | CANDIDATE BUILDER | File candidate provider gerçek inventory identity/provenance döndürür; candidate bulunması permission değildir | Resolver ayrıldıktan sonra enumeration helper sadeleşir | owner/provenance; `nxapi.allowed` execution invariant remains |
| BRAIN-MIG-031 | main_documents.py:_resolve_doc reference selection | 'son dosya/yüklediğim/bu dosya' + exact/stem seçim | engine_intents doc_* | Genel reference inference domain içinde gömülü | MOVE_TO_REFERENCE_RESOLVER | REFERENCE RESOLVER | Brain file candidates üzerinde confidence/ambiguity uygular | No implicit file resolution caller kalınca | ambiguous must not mutate |
| BRAIN-MIG-032 | main_documents.py:_file_command global entry | Quoted path/follow-up doğal dilini router öncesi çalıştırır | engine_commands.handle | Canonical Brain'i bypass eden geniş execution entry | RETIRE_AFTER_CUTOVER | CORE entry adapter | Brain `capability_hint` + bounded reference/arguments önerir; Core canonical file capability/action mapping'ini doğrulayıp aynı execution adapterini dispatch eder | Text/file UI parity acceptance sonrası pre-route call silinir | file permissions/output evidence |
| BRAIN-MIG-033 | main_documents.py/workbench.followup | 'şu sütunu ekle' gibi son tablo follow-up | _file_command | Domain-specific last artifact reference pocket | MOVE_TO_REFERENCE_RESOLVER | REFERENCE RESOLVER | Workbench artifact candidate ActiveContext'e çıkar | Brain resolver follow-up reference proposal'ı verir; Core effect targetını doğrular | artifact identity/no stale edit |
| BRAIN-MIG-034 | app_actions.py:_check_reference | task/note/event/kb/goal/fact/rule id varlığını doğrular | app_actions.run/voice | Gerçek kayıt invariant'ı; understanding'e taşınmamalı | KEEP_DOMAIN_INVARIANT | SEMANTIC INVARIANTS / domain | Resolved reference id ile aynı validation sürer | Silinmez | wrong owner/nonexistent record |
| BRAIN-MIG-035 | nxapi.allowed + main_documents path checks | Dosya kök erişim sınırı | main_documents/file ops | Gerçek filesystem safety invariant | KEEP_DOMAIN_INVARIANT | SEMANTIC INVARIANTS / domain | Candidate/reference permission değildir; Core/domain execution gerçek effect öncesi `nxapi.allowed`/symlink/allowed-root guard'ı yeniden doğrular | Silinmez | allowed roots/symlink |
| BRAIN-MIG-036 | goal_tools._pc_owner | Telefon/başka foreground owner için fiziksel PC engeli | goal_tools.execute | Gerçek execution authority/invariant | KEEP_DOMAIN_INVARIANT | CORE/domain invariant | Canonical `owner` korunur; transport/source bilgisi gerekiyorsa request/input envelope'dan taşınır, yeni `UnderstandingResult.source` field'ı icat edilmez | Silinmez | foreground owner/source |
| BRAIN-MIG-037 | task_agents._gate/runtime_execution_gate | Worker öncesi identity/state/permission/effect gate | task_agents worker loop | Gerçek güvenlik ve execution gate; Brain intent işi değil | KEEP_DOMAIN_INVARIANT | CORE | Core-validated capability aynı gate'ten geçer | Silinmez | identity/approval/effect |
| BRAIN-MIG-038 | app_actions.py:run | Typed action validate + bridge/system execution | engine_intents; app_actions.voice | Capability execution; genel anlamaya karıştırılmamalı | KEEP_EXECUTION | CORE → WORKER | Brain `capability_hint` + typed arguments/reference önerir; Core gerçek action mapping'ini doğrular ve dispatch eder | Silinmez; compatibility wrapper sadeleşebilir | typed args/result |
| BRAIN-MIG-039 | engine_intents.py:dispatch execution arms | Resolved intent'i mevcut capability'lere bağlar | engine_commands.handle | Bugün router schema'sına bağlı compatibility dispatcher | KEEP_EXECUTION | CORE dispatch adapter | Core canonical manifest/domain invariant ile `capability_hint`→capability/action mapping'ini doğrular | Legacy intent enum kalkınca adapter bölünebilir | same execution/result |
| BRAIN-MIG-040 | engine_intents.py:clarify arm | Generic pending_request üretir | router.classify result | Confidence/ambiguity kararı legacy router'a ait | RETIRE_AFTER_CUTOVER | CONFIDENCE / AMBIGUITY | Brain canonical clarification proposal/state inputunu üretir | No router clarify callers | no guessed target |
| BRAIN-MIG-041 | app_actions.py:continue_voice clarify reroute | Soru+cevabı string birleştirip router.classify tekrar çağırır | command_manager.dispatch | Recursive mini-brain; provenance kayboluyor | RETIRE_AFTER_CUTOVER | UNDERSTANDING / REFERENCE RESOLVER | Brain continuation input structured olmalı | Canonical clarification resume geçince | same owner/expiry |
| BRAIN-MIG-042 | engine_commands.py:typo recursive runtime.handle | Düzeltilmiş komutla tam pipeline'ı tekrar çağırır | engine_commands.handle | Recursive reroute; state/priority iki kez değerlendirilebilir | RETIRE_AFTER_CUTOVER | UNDERSTANDING preprocessing | Original/normalized text gerekiyorsa request/input envelope üzerinden taşınır; migration map yeni zorunlu `UnderstandingResult` alanı tanımlamaz | No recursive handle needed | single request identity/no double effect |
| BRAIN-MIG-043 | engine_commands.py:app open regex | '<app> aç/başlat/çalıştır' direct open_app | engine_commands.handle | Cross-domain target semantics ve router bypass | MOVE_TO_UNDERSTANDING | UNDERSTANDING | Brain exact/bounded app-open grammarı fast gate kriteriyle yeniden kanıtlar ya da `capability_hint` + arguments/reference proposal'ına alır; Core mapping'i doğrular | Parity sonrası legacy regex silinir | never open pronoun/unknown |
| BRAIN-MIG-044 | engine_commands.py:app close regex | '<app> kapat' direct pending_confirm | engine_commands.handle | Cross-domain target + destructive effect selection | MOVE_TO_UNDERSTANDING | UNDERSTANDING | Brain app-close `capability_hint` + target reference önerir; Core gerçek capability/action mapping'i ve confirmation/effect policy'yi doğrular | Parity sonrası legacy regex silinir | confirmation/no wrong app |
| BRAIN-MIG-045 | engine_commands.py:weather NL regex + _city_in | Hava intent ve şehir çıkarımı | engine_commands.handle | Weather için ayrı genel mini-router/reference extractor | MOVE_TO_UNDERSTANDING | UNDERSTANDING + REFERENCE RESOLVER | Brain weather `capability_hint` + location arguments/reference önerir; Core weather mapping'ini doğrular | Router/fast duplicate kapandıktan sonra | airport false-positive/location |
| BRAIN-MIG-046 | engine_tools.py:_weather | Weather provider execution + city pref fallback | engine_intents; engine_commands | Execution doğru; pending slot üretimi canonical state'e bağlanmalı | KEEP_EXECUTION | CORE → weather worker | Core-validated weather request resolved location/slot inputuyla worker'a gider | Silinmez | provider failure/no false success |
| BRAIN-MIG-047 | profile.data.prefs.city | Kayıtlı varsayılan şehir | engine_tools._weather | Domain-owned user preference; Brain copy etmemeli | MOVE_TO_ACTIVE_CONTEXT | ACTIVE CONTEXT | Read-only preference view | Storage kalır | owner scoped |
| BRAIN-MIG-048 | main_planner.py:_note_text/_note_fix | Not intent/body + 'son notu düzelt' follow-up parser | engine_tools planner/commands | Reference+intent inference organizer domaininde gömülü | MOVE_TO_UNDERSTANDING | UNDERSTANDING / REFERENCE RESOLVER | Brain note `capability_hint` + bounded target reference/arguments önerir; Core gerçek note action mapping'ini doğrular | Legacy pre-route note parser silinir | don't mutate wrong note |
| BRAIN-MIG-049 | main_planner.py:_last_note 15dk pocket | Kısa düzeltmede son not zaman penceresi | _note_fix | Ephemeral reference context ayrı dict'te | MOVE_TO_ACTIVE_CONTEXT | ACTIVE CONTEXT | Last created note event/id+gerçek timestamp read-only view | Legacy dict caller kalmayınca | 15m scope/owner |
| BRAIN-MIG-050 | main_planner.py day/week/agenda regex | Takvim/plan doğal dil isteğini yakalar | engine_tools planner path | Global NL routing organizer implementationına gömülü | MOVE_TO_UNDERSTANDING | UNDERSTANDING | Brain organizer `capability_hint` + typed date arguments önerir; Core canonical organizer/calendar mapping'ini doğrular | Pre-route parser kaldırılır | date semantics/calendar owner |
| BRAIN-MIG-051 | engine_tools.py:_mail_handle | Outlook/Gmail/meeting/draft doğal dil cascade | _extra_commands | Mail capability için ikinci router; router mail intent ile duplicate | RETIRE_AFTER_CUTOVER | UNDERSTANDING→CORE | Brain communication/mail `capability_hint` + arguments/reference önerir; Core canonical capability/action mapping'ini doğrular, domain parser yalnız bounded args işler | No pre-Brain mail handle caller | provider/account invariants |
| BRAIN-MIG-052 | engine_tools.py:_extra_commands cascade | finance/plugin/handoff/folder/browser/tasks/kb/file/media/mail/notify zinciri | engine_commands macros/extra | En geniş legacy mini-router; ilk eşleşen kazanıyor | RETIRE_AFTER_CUTOVER | UNDERSTANDING→CORE | Brain semantic proposal üretir; Core-validated domain capability adapterlerine bağlanır | Capability parity matrisi yeşil olunca cascade entry silinir | no behavior loss |
| BRAIN-MIG-053 | finance_alert_commands.matches/handle pre-Brain | Finans alarm NL girişi | engine_tools._extra_commands | Finance domain parser global entryde domain seçiyor | RETIRE_AFTER_CUTOVER | UNDERSTANDING→finance | Brain finance-alert `capability_hint` + arguments önerir; Core mapping'i ve domain validation'ı doğrular | Pre-Brain matches call kaldırılır | finance evidence/domain contract |
| BRAIN-MIG-054 | watcher.py:handle global entry | Klasör izleme NL girişini doğrudan yakalar | engine_commands.handle | Brain'den önce capability/domain seçiyor | RETIRE_AFTER_CUTOVER | UNDERSTANDING→watcher | Brain watcher `capability_hint` + arguments önerir; Core canonical watcher mapping'ini doğrular | No pre-Brain watcher caller | allowed folder/rule limit |
| BRAIN-MIG-055 | watcher.py:_WATCH/_WHEN/action parser | Seçilmiş watcher komutundan klasör/ext/action çıkarır | watcher.handle | Domain grammar; global router olmak zorunda değil | KEEP_EXECUTION | WORKER/domain parser | Core Brain proposal'ını watcher capability'ye doğruladıktan sonra aynı bounded parser input adapteri olabilir | Silinmez; sadece entry değişir | folder allowlist/limits |
| BRAIN-MIG-056 | watcher.py:scan/process/tick | Dosya tarama, stability, quota, execution | watcher loop | Gerçek worker execution | KEEP_EXECUTION | WORKER | Brain yalnız user-triggered semantic proposal üretir; background loop domain-owned | Silinmez | done/stability/hourly cap |
| BRAIN-MIG-057 | watcher.py durable rules + _STATE/_RECENT | İzleme rule truth + scan/runtime counters | watcher loop | Brain ikinci state kopyası oluşturmamalı | MOVE_TO_ACTIVE_CONTEXT | ACTIVE CONTEXT | Read-only watcher status provider ilgili migration/cutover öncesinde incremental eklenebilir; PR2 zorunlu dependency değildir | Storage/counters domain-owned kalır | owner/rule id |
| BRAIN-MIG-058 | hoca.py:context_for/active/current_step | Aktif ders/adım read-only context | engine_tools._study_intent/live prompt candidates | İyi domain-owned source; genel contextte standart değil | MOVE_TO_ACTIVE_CONTEXT | ACTIVE CONTEXT | Hoca provider typed lesson summary verir | Storage kalır | owner/course/step |
| BRAIN-MIG-059 | hoca.py:intent | Aktif Hoca içinde next/change/stay domain grammar | hoca.handle | Domain continuation parser; genel intent router olmamalı | KEEP_EXECUTION | WORKER/domain parser | Brain `conversation_relation`/`capability_hint` semantic proposal üretir; Core Hoca mapping'ini doğrular, parser yalnız aktif lesson içinde bounded grammar işler | Silinmez | explicit next/change only |
| BRAIN-MIG-060 | study.last_topic fallback | Görsel/video için son ders konusu | engine_tools._study_intent | Ephemeral domain reference; source canonical timestamp taşımıyor | MOVE_TO_ACTIVE_CONTEXT | ACTIVE CONTEXT | Study provider read-only `last_topic` verebilir; source timestamp yoksa age üretilmez ve recency `UNSURE` kalır | Legacy direct lookup sonrası | owner/course/no invented age |
| BRAIN-MIG-061 | visual_chat.py:_history_text | Son 40 history satırını görsel içerik yapar | visual_chat.handle | Ad-hoc context assembly; relevance/provenance yok | MOVE_TO_ACTIVE_CONTEXT | ACTIVE CONTEXT | Bounded conversation span/artifact canonical references üzerinden önerilir | Visual handler raw history okumayınca | owner/reset |
| BRAIN-MIG-062 | session_state.py:last_visual | Retry için önceki visual request/content/kind | visual_chat.handle; main_documents | Kısa süreli artifact reference pocket | MOVE_TO_ACTIVE_CONTEXT | ACTIVE CONTEXT | Last visual artifact reference + gerçek provenance | Legacy dict caller kalmayınca | owner/no cross-chat |
| BRAIN-MIG-063 | visual_commands.detect_type_by_keyword/model | Görsel türü semantik sınıflandırması | visual_chat; create_visual | Global sohbet girişinde mini intent sınıflandırıcı; model fallback ikinci brain çağrısı | MOVE_TO_UNDERSTANDING | UNDERSTANDING | Brain visual `capability_hint` + subtype bilgisini mevcut `arguments` içinde önerir; yeni zorunlu field tanımlanmaz | Visual entry canonical olunca detect yalnız explicit button fallback olabilir | visual subtype corpus |
| BRAIN-MIG-064 | visual_commands.create_visual | Prompt build + image generation + save | visual_chat/main_documents | Gerçek capability execution | KEEP_EXECUTION | WORKER | Core-validated subtype/content alır | Silinmez | output path/image failure |
| BRAIN-MIG-065 | learning.py:rules/facts/pending + prompts | Behavior/memory domain-owned durable state | profile/live/chat system prompt | Context source; authority olmamalı | MOVE_TO_ACTIVE_CONTEXT | ACTIVE CONTEXT | Memory candidate provider relevance+provenance ile read-only | Storage kalır; direct prompt injection kalkar | rules cannot override permission/core |
| BRAIN-MIG-066 | learning.py:query_scopes/rule_scope | Komuta göre ilgili davranış kuralı seçimi | rules_prompt | Relevance/candidate selection Brain dışında regex mini-selector | MOVE_TO_CANDIDATE_BUILDER | CANDIDATE BUILDER | Memory provider candidates; Brain relevance değerlendirmesi bounded candidate set üstünde yapılır | Direct rules_prompt query filtering kalkınca | global rules + scoped rules |
| BRAIN-MIG-067 | goal_executor.py:latest/is_open/status | Durable GoalState truth ve open/stale görünümü | engine_commands/job_front/queue | Canonical execution state; Brain ikinci lifecycle yaratmamalı; bu source kendi başına açık uçlu utterance consume etmez | KEEP_STATE_GATE | EXACT STATE GATE state source | Read-only GoalState summary ActiveContext'e eklenir; yalnız explicit deterministic resume/cancel/status protokolleri exact gate olabilir | Silinmez | CAS/owner/stale/no broad consume |
| BRAIN-MIG-068 | goal_executor.py:_planner/_loop/run | Durable goal planning/execution | engine_intents task; explicit goal | Core execution/planning; understanding brain ile karıştırılmamalı | KEEP_EXECUTION | CORE | Brain canonical `capability_hint`/`arguments`/`references` proposal'ı Core'a girer; Core plan/execution authority'sini korur | Silinmez; compatibility request parser sadeleşir | permission/evidence/completion |
| BRAIN-MIG-069 | completion_policy.py + goal_executor completion checks | Global completion evidence policy | goal_executor | Canonical Core completion; worker/agent'e taşınmamalı | KEEP_EXECUTION | CORE | Brain yalnız semantic proposal/result verir; completion Core'da | Silinmez | no false done |
| BRAIN-MIG-070 | task_agents.py:handle natural-language admin entry | 'görev akışı/devam/iptal/geçmiş' legacy entry | command_manager.dispatch/job_front | İkinci task front door ve genel NL interception | RETIRE_AFTER_CUTOVER | CORE entry | Brain task continuation semantics önerir; Core GoalState/capability mapping'ini doğrular | Legacy task front door callers sıfırlanınca | existing job recovery |
| BRAIN-MIG-071 | task_agents.py durable DAG/worker/_gate | Legacy durable specialist execution | task_agents.handle/specialist bridge | Gerçek execution/evidence; cutover planı dışında aniden silinemez | KEEP_EXECUTION | AGENTS / WORKERS | Core compatibility adapter altında kalır | GoalState canonical replacement + data migration kanıtı sonrası ayrıca karar | recovery/evidence/owner |
| BRAIN-MIG-072 | task_agents.py:recent | Son task job seçimi | job_front | Durable task state lookup; active contextte read-only olmalı | MOVE_TO_ACTIVE_CONTEXT | ACTIVE CONTEXT | Legacy task summary provider | Task engine emekli olunca | owner/stale |
| BRAIN-MIG-073 | advisory_router.py:_mode | decision/critique/guidance isteğini doğal dilden seçer | engine_tools._sys_prompt; finalize | Genel NL interpretation; Brain ile aynı resolved context'i kullanmalı | MOVE_TO_UNDERSTANDING | UNDERSTANDING → ADVISOR handoff | Canonical Understanding doğal dilde advisory ihtiyacını çözer; migration map yeni zorunlu `UnderstandingResult` field'ı dayatmaz | Legacy requested() regex entry kalkınca | explicit advisory request; no execution/permission authority |
| BRAIN-MIG-074 | advisory_router.py:finalize + advisor renderers | Resolved advisory output schema/render | chat fallback | Execution/permission authority yok; response shaping | KEEP_EXECUTION | Advisor layer after Understanding | Brain resolved context + chat result ile beslenir | Silinmez | no dispatch/no permission |
| BRAIN-MIG-075 | proactive_advisor.SuggestionPolicy | Suggestion enable/filter/render | advisory_router | İkinci Core değil; yalnız advisory output | KEEP_EXECUTION | ADVISOR | Resolved context ile suggestion üretir | Silinmez | no execution authority |
| BRAIN-MIG-076 | engine_voice.py:_live_prompt | Live için goals/facts/rules/pending/history/STT context kurar | engine_loop → live.start | Text Brain'den ayrı context snapshot; drift riski | MOVE_TO_ACTIVE_CONTEXT | ACTIVE CONTEXT | Live aynı ActiveContext serializer'ı kullanır | Private live prompt context assembly kaldırılır | owner/redaction/reset |
| BRAIN-MIG-077 | engine_voice.py:_context_prompt | Live modele son 2 saati verip 'onu/az önceki' çözmesini söyler | _live_prompt | Ayrı reference resolver fiilen Live modelin içinde; 2h pencere legacy consumer davranışıdır, canonical global history TTL değildir | MOVE_TO_REFERENCE_RESOLVER | REFERENCE RESOLVER | Live utterance canonical resolver/UnderstandingResult kullanır; source timestamp/reset boundary korunur | Live model kendi pronoun resolution authority'sini bırakınca | text/live parity; legacy 2h parity where required |
| BRAIN-MIG-078 | live_tool_runner.py special direct tools | muzik_cal/_play_music, handoff, mishearing, voice change direct yolları | Live function-call model | Normal Brain/router/Core'u kısmen bypass ediyor | RETIRE_AFTER_CUTOVER | Canonical Brain entry | Live function call önce Brain semantic proposal'ından geçer; Core capability/action mapping'ini doğrular, execution aynı worker'a gider | Live parity acceptance sonrası direct semantic dispatch kaldırılır | permission/source parity |
| BRAIN-MIG-079 | engine_voice.py:_live_command | Live `komut` toolunu normal runtime.handle'a köprüler | live_tool_runner/live session | İyi compatibility entry; request identity/source korunuyor | KEEP_EXECUTION | Brain entry adapter | runtime.handle içinde Brain + Core canonical olur | Live tool surface sadeleşince adapter kalabilir | same request owner/source |
| BRAIN-MIG-080 | engine_queue.py:submit command queue | Text/Web/Phone komutlarını aynı engine eventine taşır | UI/phone server | Transport execution; intent çözmüyor | KEEP_EXECUTION | Brain entry transport | Event consumer Brain entry çağırır | Silinmez | request id/owner/cancel |
| BRAIN-MIG-081 | engine_queue.py:direct goal status branch | 'hedef durumu/işin durumu/hedef ayrıntıları' queue içinde render | UI/phone submit | Canonical Brain/engine handle'ı bypass eden transport-level intent | RETIRE_AFTER_CUTOVER | EXACT STATE GATE | Exact state query Brain State Gate'e taşınır | All transports same Brain entry olunca | same status text/owner |
| BRAIN-MIG-082 | engine_queue.py:submit_audio STT→command | Phone audio transport | phone server/engine loop | Transport; command path sonunda aynı handle'a gitmeli | KEEP_EXECUTION | Brain entry transport | STT text doğrudan aynı Brain entry | Silinmez | owner/rid |
| BRAIN-MIG-083 | engine_commands.py bare objectless verb pending_request | 'aç/kapat/sil/gönder' için clarification | engine_commands.handle | Ambiguity detection legacy regex'te, Brain confidence'dan önce | MOVE_TO_UNDERSTANDING | CONFIDENCE / AMBIGUITY | Brain unresolved target => canonical clarification proposal | Parity sonrası regex silinir | never guess target |
| BRAIN-MIG-084 | engine_commands.py bare number pending_level | '70 yap' → volume/brightness clarification | engine_commands.handle | State sonucu doğru ama ambiguity detector global legacy | MOVE_TO_UNDERSTANDING | CONFIDENCE / AMBIGUITY | Brain candidate set + confidence ile clarification proposal üretir | Detector silinir; pending state korunur | bounded 0-100 |
| BRAIN-MIG-085 | command_manager.py → developer.handle | Geliştirme modu aktifken genel komutları kendi turn/memory/tool loop'una alır | command_manager.dispatch | Uzman agent kendi sohbet bağlamı ve genel continuation yorumunu taşıyor; aktif mod sınırı nedeniyle migration şekli sözleşme kararı ister | NEEDS_DECISION | UNDERSTANDING / AGENT boundary | Brain Contracts mevcut `capability_hint`/references/request relation ile developer semantic proposal'ını ifade eder; Core authenticated developer mapping'ini doğrular | Global interception Core-validated worker handoff'a geçtiğinde kaldırılır | auth/draft/test/apply invariants |
| BRAIN-MIG-086 | developer.py:state.turns/state.memory/_old_turns | Uzman-local conversation ve memory | developer._turn | Genel chat memory gibi kullanılma riski; fakat proje-local worker scratchpad olabilir | MOVE_TO_ACTIVE_CONTEXT | ACTIVE CONTEXT | Yalnız developer task-scoped context provider olarak expose edilir; global truth yapılmaz | Global command reference için kullanım bitince | owner/auth/project scope |
| BRAIN-MIG-087 | developer.py:handle exact draft/apply/test commands | Taslak göster/test/apply/undo gibi bounded domain protocol | command_manager.dispatch | Aktif developer modunda hedef açık, grammar bounded; unrelated serbest metin bu exact protocol sınıfına girmez | KEEP_STATE_GATE | EXACT STATE GATE | Active developer session state + exact protocol Brain gate'e görünür | Silinmez; entry adapter sadeleşebilir | password/auth, no auto-apply, fresh test, no broad consume |
| BRAIN-MIG-088 | command_manager.py → desktop_agent.handle | PC görevi doğal dilini pre-Brain yakalar | command_manager.dispatch | Agent global intent/domain interception yapıyor | RETIRE_AFTER_CUTOVER | UNDERSTANDING→CORE | Brain desktop `capability_hint` + arguments/reference önerir; Core canonical desktop/GoalExecutor mapping'ini doğrular | No pre-Brain desktop_agent.handle caller | Core prepare/approval/evidence |
| BRAIN-MIG-089 | desktop_agent.py:validate/_permission_decision/_perform | UIA target/effect/permission/evidence uygulaması | goal_tools/task workers/legacy desktop entry | Gerçek domain invariant + effect execution; Brain'e taşınmamalı | KEEP_DOMAIN_INVARIANT | SEMANTIC INVARIANTS / WORKER | Core-validated desktop goal mevcut gate'e gelir | Silinmez | target identity, secret/outbound block, verification |
| BRAIN-MIG-090 | smart_router.py:task_type | Prompttan code/analysis/chat/vision provider sınıfı seçimi | smart_router.run | Bu user intent router değil provider capability sınıfı; Brain migration kapsamındaki yeri tam contracta bağlı | NEEDS_DECISION | post-Understanding provider routing | Canonical `capability_hint`/`arguments` provider routing için yeterli semantic sinyal sağlarsa duplicate kaldır; yoksa provider-local classifier kalır; yeni `task_kind` field'ı icat edilmez | Contracts sonrası tek owner belirlenir | zero-cost/privacy/provider evidence |
| BRAIN-MIG-091 | smart_router.handle / usage_meter.handle / system_doctor.handle exact admin commands | Router/kota/tanı config/status exact komutları | command_manager.dispatch | Bounded admin grammar; target açık ve cross-domain inference yok | KEEP_FAST_GATE | DETERMINISTIC FAST GATE | Exact registry altında testli kalır | Silinmez; ortak fast gate'e taşınabilir | no paid enable without evidence; exact commands |

## 3. Duplicate execution path matrisi

Buradaki “duplicate”, aynı kullanıcı capability'sine birden fazla **entry/selection** yolu olduğu anlamındadır; alttaki gerçek worker'ın paylaşılması tek başına duplicate sayılmamıştır.

| Capability | Yol A | Yol B / ek yol | Hangisi canonical kalmalı | Diğeri ne zaman silinir |
|---|---|---|---|---|
| weather | engine_commands weather regex → _weather | router.classify(weather) → engine_intents → _weather | Brain weather semantic proposal (`capability_hint` + location args/reference) → Core doğrulaması → tek weather execution adapter | Legacy pre-route regex ve router intent duplicate parity sonrası |
| finance | engine_tools._extra_commands → finance_alert_commands | router freshness/task → goal_executor finance/data | Brain finance semantic proposal → Core canonical finance mapping'i; alarm domain parser yalnız Core-validated finance.alert altında | Pre-Brain finance matches kaldırılınca |
| media | engine_commands/media legacy yolları + engine_tools.media.handle | router intent=media → engine_intents; Live muzik_cal direct | Brain media `capability_hint`/arguments proposal'ı → Core doğrulaması → aynı execution/effect gate | Direct Live/legacy media dispatch parity sonrası |
| volume/brightness | engine_commands pending_level/direct regex | router volume/brightness → engine_intents | Brain pc.setting `capability_hint` + arguments proposal'ı; Core mapping'i doğrular; bounded pending state exact gate olabilir | Legacy regex paths parity sonrası |
| app open/close | engine_commands direct app regex | router open_app/close_app → engine_intents/app_actions | Brain app `capability_hint` + target reference proposal'ı → Core doğrulaması → command_execution/app action | Direct pre-route regex sonrası |
| file/document | engine_commands → main_documents._file_command | router doc_* → engine_intents → _resolve_doc | Brain candidate+resolver bounded reference proposal'ı → Core file capability/action doğrulaması → execution adapter | _file_command global entry ve embedded resolver sonrası |
| note/calendar | main_planner pre-route regex/helpers | router note/app_action event_* | Brain semantic/reference proposal → Core profile/calendar capability/action doğrulaması → execution | Legacy planner intent parser sonrası |
| mail | engine_tools._mail_handle/Google/Outlook handles | router mail → engine_intents; task_agents account worker | Brain communication/mail `capability_hint` + args/reference proposal'ı; Core gerçek provider/capability mapping'ini ve fast-vs-durable yolu doğrular | Pre-Brain mail cascade sonrası |
| research | freshness/work_modes → router task | explicit goal/task → goal_executor; task_agents research legacy | Brain `temporal_need` + research semantic proposal → Core canonical research capability mapping'i | Legacy task_agents front door ve freshness route sonrası |
| visual | visual_chat keyword/pending → visual_commands | main_documents visualize; Live/model tools where applicable | Brain visual `capability_hint` + subtype `arguments` proposal'ı; Core mapping/source validation; bounded source pending exact gate olabilir | Global keyword detector entry after parity |
| translation | command_manager → chat_translation.resolve | router translate/doc_translate → engine_intents/main_documents | Brain resolver bounded source reference + translation `capability_hint` önerir; Core mapping'i doğrular | chat_translation resolver/_sources sonrası |
| desktop | command_manager → desktop_agent.handle | router desktop_task → goal_executor → desktop worker | Brain desktop `capability_hint`/arguments/reference proposal'ı → Core/GoalExecutor canonical validation | Direct agent entry sonrası |
| developer | command_manager → developer.handle active-mode interception | goal_executor coder/task_agents coder paths | Brain developer semantic proposal → Core authenticated developer capability mapping'i | Agent-session contract sonrası |
| handoff | engine_tools._extra_commands → handoff.handle | router handoff → engine_intents; Live gorev_ekle direct | Brain handoff `capability_hint`/args proposal'ı → Core doğrulaması → one execution path | Pre-Brain + Live direct semantic dispatch sonrası |

**Toplam duplicate capability ailesi: 14.**

## 4. Canonical Active Context Sources

Kural: Brain yeni bir truth-store oluşturmaz. Domain-owned state korunur ve Brain'e yalnız **read-only ActiveContext view** verilir.

| Context kaynağı | State sahibi / saklama | Owner-scoped | TTL / yaşam | Brain read-only okuyabilir mi? | Yeni state'e kopyalansın mı? |
|---|---|---|---|---|---|
| SessionStore pending fields | SessionStore / RAM | evet | alan bazlı; bazıları source-defined TTL taşıyor, bazıları taşımıyor | evet | hayır; read-only view |
| SessionStore last_command/last_doc/last_visual | SessionStore / RAM | evet | çoğunda explicit timestamp/TTL yok; recency bilinmiyorsa `UNSURE` | evet | hayır; yalnız gerçek provenance, uydurma age yok |
| Conversation history | history store / durable | evet | source timestamp'leri korunur; reset/session boundary + bounded read; **canonical global 2h TTL yok** | evet | hayır |
| chat session reset epoch | chat_translation chat_sessions.json / durable | evet | reset boundary | evet | hayır |
| GoalState/latest job | goal_executor store / durable | evet | STALE_SECONDS semantics | evet | hayır |
| Legacy task DAG/latest | task_agents store / durable | evet | job semantics | evet | hayır; compatibility view |
| Profile tasks/notes/events/goals/facts/rules/prefs | profile data / durable | evet | domain-dependent | evet | hayır |
| Hoca lesson/current step/pending question | profile.data[hoca] / durable | evet | lesson lifecycle | evet | hayır |
| Study last topic/docs | study state / durable/profile-backed | evet | `last_topic` için canonical timestamp yok; recency `UNSURE` olabilir | evet | hayır |
| Watcher rules | DATA_DIR/izleme / durable | evet | rule lifecycle | evet, ilgili migration öncesinde incremental provider ile | hayır |
| Watcher runtime counters/pending quota | watcher RAM | evet | 1h recent quota window / process lifetime | evet, gerektiğinde status source | hayır |
| Workbench last artifact/job | workbench domain state | evet | implementation-specific recent state | evet | hayır |
| Developer turns/memory/draft state | developer store / durable | evet | developer-session scope | evet, yalnız task-scoped | hayır |
| Provider/router health/evidence | smart_router owner state + RAM | evet | evidence TTL/cooldown | gerektiğinde | hayır |
| Current transport source/request id | EngineContext / request state RAM | evet | request lifetime | evet | hayır |
| Foreground PC owner | EngineContext pc_profile / runtime | evet | runtime lifetime | evet | hayır |

**Toplam canonical Active Context source ailesi: 16.** Bu tablo source envanteridir; bütün provider'ların PR2'de bir kerede implemente edilmesi gerektiği anlamına gelmez. Merge edilmiş PR2 canonical ActiveContext builder foundation + SessionStore + bounded history + GoalState + dar `profile.prefs.city` + Hoca lesson/pending ile başlamıştır. Watcher ve diğer domain-owned provider'lar ilgili migration/cutover öncesinde incremental, read-only ve ikinci truth-store yaratmadan eklenebilir.

### Legacy context pockets

Gerçek konuşma/intent/reference bağlamı taşıdığı doğrulanan cepler:

- `SessionState.last_command`, `last_doc`, `last_visual`, `pending_request`, `pending_visual`, `pending_app` ve diğer `pending_*` alanları.
- `chat_translation._sources` ve durable reset epoch'u.
- `main_planner._last_note`.
- `workbench` son artifact/job state'i.
- `study.last_topic` / Hoca current step.
- developer `state.turns` / `state.memory`.
- Live `_recent_user` ve `_context_prompt` history görünümü.
- watcher `_PENDING` gerçek operational quota/background state'tir; `_RECENT` kota penceresidir. Bunlar global sohbet hafızası veya EXACT STATE GATE değildir ve unrelated kullanıcı mesajını consume etmemelidir.
- `smart_router._LAST`/health benzeri provider operational kayıtları conversation reference değildir; Brain memory olarak taşınmamalıdır.

İsim eşleştiği halde bağlam bulgusu sayılmayan örnekler: performans ölçümündeki `last_*`, audio timing, cursor/update counters, UI widget timestamps. Bunlar Brain context'i değildir.

## 5. Test sınıflandırması

### PRODUCT INVARIANT — korunacak

Aşağıdaki test davranışları implementation değişse bile korunmalıdır:

- owner/request identity eşleşmesi; başka kullanıcının GoalState, task, note, file, developer veya PC state'ine erişmeme.
- stale approval/pending selection tüketmeme; yalnız source-defined TTL ve cancel semantics.
- ambiguous reference ile mutate/send/open/close yapmama.
- nonexistent record/path/candidate üzerinde effect üretmeme.
- `nxapi.allowed`, symlink/path sınırları ve desktop target identity.
- permission/effect policy olmadan outbound/destructive action çalıştırmama.
- worker sonucunu global completion saymama; completion evidence/Core policy.
- Live/Phone source nedeniyle fiziksel PC owner invariantını bypass etmeme.
- memory/rules'ın permission, Domain Invariant, Decision Authority veya Effect Policy'yi geçersiz kılamaması.
- current-data/research isteğinin stale/static cevap yoluna sessizce düşmemesi.
- clarification'da farklı bir yeni isteğin eski pending işlemi yanlışlıkla onaylamaması veya unrelated utterance'ın açık uçlu pending cevabı sayılmaması.
- document/reference resolution'da owner ve gerçek artifact identity'nin korunması.

### LEGACY IMPLEMENTATION TEST — migration sırasında yeniden yazılabilir

Eski regex sırası, belirli helper çağrısı, `router.classify` intent enum'u, `engine_commands.handle` içindeki branch sırası veya tam prompt string'ini kilitleyen testler product invariant değildir. Bunlar yeni Brain'de aynı kullanıcı outcome'unu doğrulayacak şekilde güncellenmelidir.

`tests/data/yonlendirme_cumleleri.json` **silinmemeli**. İçindeki gerçek kullanım cümleleri regression corpus olarak korunmalıdır: chat-vs-action, weather, app open/close, volume/brightness/media, mail, note/handoff, translation, doc convert, finance/current-data, research, ambiguous pronouns ve multi-step örnekleri yeni Brain acceptance setine taşınmalıdır. Ancak `model`/`beklenen` alanları yeni Brain için “regex kural kitabı” değildir; corpus outcome/confidence/capability regression verisidir. `bilinen_hata`, `bekletilmis`, `tartismali` gibi metadata da overfit ölçümü için korunabilir.

## 6. Text / Voice / Live / Phone Brain Entry Matrix

| Giriş | Bugün gördüğü history/context | Router bypass? | Kendi tool/intent çözümü? | Canonical Brain bağlantısı |
|---|---|---|---|---|
| Text/Web | history + SessionStore + profile; **legacy router consumer** son 2 saatten 6 turn kullanıyor | genelde hayır; fakat queue direct goal-status bypass var | router + çok sayıda pre-router handler | engine_queue/event → tek Brain entry; canonical ActiveContext bounded history + reset boundary kullanır, global 2h TTL tanımlamaz; state query State Gate |
| Voice (non-Live STT) | aynı SessionStore/history; source=ses | hayır; normal handle'a girer | normal engine router | STT text doğrudan aynı Brain entry |
| Live | _live_prompt profile/facts/rules/pending + **legacy consumer** son 2 saat 12 turn; Live-local recent_user | evet, bazı özel tools normal handle'ı bypass ediyor | Live model kendi tool selection + context/reference çözümü | her utterance/tool intent canonical Brain UnderstandingResult; Live yalnız transport/voice surface; legacy 2h parity gerekiyorsa migration testi olarak korunur, canonical TTL olmaz |
| Phone text | owner/request id + normal session/history | queue'daki goal-status exact branch bypass ediyor | sonrasında normal handle | queue yalnız transport; exact status State Gate dahil Brain entry |
| Phone audio | STT sonrası phone owner/rid + normal session | STT sonrası normal command path | normal engine router | STT result aynı Brain entry |
| Phone photo | pending photo + question; session/owner | foto event/pending branch özel | photo follow-up parser engine_commands | artifact state ActiveContext'te görünür; exact cancel bounded gate olabilir; açık uçlu follow-up relation'ı Understanding çözer ve artifact Resolver'a bounded candidate olarak sunulur; unrelated message photo follow-up diye consume edilmez; vision execution worker |

Önemli parity sonucu: non-Live ses ve normal text aynı `runtime.handle()` hattına yakınken, **Live tam eşit değildir**. `_live_prompt` ayrı context/reference talimatı kurar ve `live_tool_runner` bazı özel araçları normal handler'dan bağımsız çalıştırır. Phone text de queue katmanındaki direct goal-status branch nedeniyle küçük bir bypass taşır.

## 7. Advisor katmanı

`advisory_router.py` kodu açıkça work dispatch, GoalState write, permission check veya worker execution yapmıyor. Bu nedenle decision/critique/guidance/proactive mekanizmaları ayrı bir genel Core/Brain olarak değerlendirilmemelidir.

Migration kararı:

- `advisory_router._mode` ve `decision_advisor.requested` / `critique_advisor.requested` / `guidance_advisor.requested` doğal dil seçimi canonical Understanding/Advisor katmanına taşınır.
- Migration map, Brain Contracts implementation'ından bağımsız yeni bir `advisor_mode` veya başka zorunlu `UnderstandingResult` schema field'ı tanımlamaz.
- schema validation/render/finalize ve proactive suggestion policy **Advisor output layer** olarak kalabilir.
- Advisor aynı canonical resolved context'i tüketmeli; kendi history/reference resolver'ını kurmamalı.
- Advisor'a execution, permission, target selection veya global completion authority verilmemeli.

## 8. En tehlikeli 10 legacy yol

1. engine_tools._extra_commands — çok sayıda domaini ilk eşleşen kazanır mantığıyla Brain'den önce seçiyor.
2. router.classify — regex + model + app reference context + freshness ile ikinci genel beyin.
3. command_manager.dispatch — visual/task/developer/desktop/translation/Hoca gibi birçok pre-Brain front door.
4. engine_commands.handle içindeki app/weather/note/file/sequence legacy yolları — canonical understanding öncesi davranış seçiyor.
5. app_actions.continue_voice clarify — string birleştirip router.classify recursive çağrısı yapıyor.
6. engine_commands typo recursive runtime.handle — aynı request içinde tam pipeline'ı yeniden değerlendiriyor.
7. main_documents._file_command/_resolve_doc — execution, candidate retrieval ve 'bu/son dosya' reference inference aynı yerde.
8. chat_translation.resolve + _sources — ayrı legacy 2 saatlik reference resolver ve RAM fallback truth pocket.
9. Live special tools/live prompt — ayrı context/reference/tool-selection ile text parity'yi bozuyor.
10. developer.handle / desktop_agent.handle pre-Brain interception — uzman agentların genel komut girişini sahiplenebildiği yollar.

## 9. İlk silinebilecek 5 parça

Canonical replacement ve parity testleri geldikten sonra risk sırasına göre:

1. chat_translation._sources RAM cache — canonical resolver history/provenance parity sonrası.
2. engine_queue direct goal-status render bypass — State Gate canonical entry geldiğinde.
3. app_actions clarification re-route (combined string → router.classify) — structured clarification resume geldiğinde.
4. engine_commands typo recursive handle — original/normalized representation request/input envelope üzerinden tek request identity ile taşındığında.
5. router içindeki app_actions.reference_context prompt helper — Candidate Builder providerları devreye girince.

Bu parçalar PR9/PR10'u beklemek zorunda değildir. Replacement + parity + product invariant acceptance hangi migration PR'ında tamamlanırsa ilgili legacy yol **aynı PR'da** kaldırılabilir. PR10 yalnız kalan zombie/duplicate yolların final sweep'idir.

## 10. Önerilen Migration Sırası

Canonical sıra aşağıdadır. **Active Context ve Candidate Builder Understanding'den önce** gelir; **Text/Web/Phone cutover ile Live parity ayrı PR** tutulur. Legacy retirement her aşamada replacement/parity/invariant kabulüne bağlıdır, yalnız PR9/PR10'a ertelenmez.

| PR | Girecek yollar | Çıkacak legacy yollar | Önkoşul | Acceptance |
|---|---|---|---|---|
| PR 1 — Brain Contracts | Canonical Brain contracts/types | yok | mevcut | Contracts tests; bu rapor branch'inden bağımsız |
| PR 2 — Active Context | Canonical ActiveContext builder foundation + initial/core providers: SessionStore, bounded history, GoalState, dar profile preference (`prefs.city`), Hoca lesson/pending | Replacement+parity tamamlanan initial ad-hoc context assembly parçaları | PR1 | owner isolation; no copied truth; domain state read-only; source timestamp yoksa age/TTL uydurulmaması. Diğer domain-owned providers ilgili cutover öncesinde incremental eklenebilir; watcher PR2 zorunlu dependency değildir |
| PR 3 — Candidate Builder | file/profile/memory candidate providers | Replacement+parity tamamlanan app_actions.reference_context retrieval ve _resolve_doc enumeration tarafı | PR2 | candidate provenance/owner; candidate bulunması permission değildir; `nxapi.allowed`/symlink/allowed-root guard domain invariant olarak kalır ve Core/domain execution gerçek effect öncesi yeniden doğrular |
| PR 4 — Reference Resolver | translation/file/note/visual/workbench referansları | Replacement+parity tamamlanan chat_translation authority, `_sources`, embedded `bu/son` resolvers | PR2-3 | ambiguous reference no action; reset boundary/source-defined TTL/provenance; canonical history için keyfi global TTL yok |
| PR 5 — Understanding Engine | router/work_modes/freshness/sequence doğal dil kararları; canonical `temporal_need` | Replacement+parity tamamlanan legacy classifier/semantic shortcuts | PR1-4 | yonlendirme corpus + ambiguity + temporal_need + sequence parity; yeni mandatory `UnderstandingResult` field yok |
| PR 6 — Exact State + Deterministic Fast Gates | Exact State Gate + proven deterministic fast registry | Replacement+parity tamamlanan scattered gate checks; operational watcher pending, weather open-ended location, Hoca open-ended answer, generic clarification, phone-photo açık uçlu follow-up ve WhatsApp `to`/`text` broad State Gate'e alınmaz | PR2, PR5 | exact/bounded pending precedence; owner + yalnız source-defined TTL; every fast rule six criteria; `State exists` unrelated messages'ı consume etmez |
| PR 7 — Text/Web/Phone Core Entry + Reverse Clarification / BrainFeedback | text/web/phone transport → Brain semantic result → Core validation/dispatch; structured reverse clarification ve BrainFeedback integration | Replacement+parity tamamlanan pre-router extra/file/watcher/mail/app/note entry yolları ve recursive clarification reroutes | PR3-6 | text/web/phone parity; clarification provenance; BrainFeedback round-trip; no duplicate effect; Core capability/action authority korunur |
| PR 8 — Advisor + Echo + Failure Synthesis | canonical resolved context üstünde Advisor; Echo/Semantic Preview; failure synthesis/recovery presentation | Replacement+parity tamamlanan advisory NL selector ve duplicate presentation-only legacy yollar | PR7 | Advisor no execution/permission authority; preview no effect; failure presentation grounded in structured failures; blind retry yok |
| PR 9 — Live Parity + Live-specific legacy retirement | Voice/Live aynı Brain entry/context/resolver/Core hattına | Live private reference authority ve special semantic direct dispatch; replacement+parity tamamlanan diğer Live-only legacy yollar | PR8 | text/voice/live/phone same semantic/reference outcome; Core source permissions preserved; no Live semantic bypass |
| PR 10 — Final legacy sweep + cutover acceptance | final zombie/duplicate sweep, docs/guards/test reclassification | Yalnız önceki PR'larda replacement/parity/invariant tamamlanmasına rağmen kalmış legacy/shadow yollar | PR9 | full validation; duplicate-path final sweep; no second truth source; canonical cutover acceptance |

### PR 2-10 için doğrulanan kararlar

1. Active Context + Candidate Builder, Reference Resolver ve Understanding'den önce kurulmalı.
2. PR2 initial/core provider foundation'dır; bütün domain provider'ları tek PR'a zorlanmaz. Ek provider'lar ilgili migration/cutover öncesinde incremental ve read-only eklenir.
3. Text/Web/Phone Core cutover ile Live parity aynı PR'a sıkıştırılmamalı.
4. Reverse Clarification / BrainFeedback PR7'de canonical Core entry ile birlikte bağlanmalı.
5. Advisor + Echo/Semantic Preview + Failure Synthesis/Recovery presentation PR8'de, execution/permission authority almadan aynı resolved context'i kullanmalı.
6. Legacy retirement opportunistic'tir: replacement + parity + invariant acceptance hangi PR'da tamamlanırsa o PR'da yapılabilir; PR10 final zombie/duplicate sweep'tir.

Yeni faz/özellik önerilmiyor; bu mevcut Brain migration işinin canonical bağımlılık sırasıdır.

### PR1-PR7 kapanış durumu (2026-10-31)

PR1-PR7 merge edildi ancak eski yolların silinmesi (her PR'ın "legacy retirement" görevi) yapılmadı. Kapanış iki parçadır: **Closeout-A** (continue_voice yapılandırılmış resume, history_limit üst sınırı, last_property, tek geçişli yazım düzeltme, gerçek BrainFeedback, doküman) ve **Closeout-B** (capability_hint → Core, eski router/work_modes/freshness otoritesi, regex ön kapıları, candidate/reference execution, `reference_context`, `_resolve_doc`, `chat_translation._sources`). Closeout-B'nin kabul kapısı 160 senaryolu regresyon havuzudur. Not: `engine_queue` hedef durumu kısayolu, komut döngüsü doluyken yanıt verebilmek için Brain girişinden önce çalışır; kaldırılması için Brain öncesi bir fast lane tasarımı gerekir (Closeout-B).

**Closeout-B1 sonucu:** `brain_core_map` Core allowlist'i ve `level_set` intent'i eklendi; `router.classify` yalnız Live (`_live_command`) gibi Brain'e girmeyen çağıranlar için duruyor ve PR9'da Live bağlanınca caller-zero olarak silinecek. `work_modes`'u router'ın yanında `goal_executor` (`ends_with_action`) çağırıyor; bu çağrı B2'de Brain kararına taşınacak. `freshness`'ı yalnız router kullanıyor. `engine_queue` kısayolu `brain_entry.fast_lane` üzerinden Brain Fast Gate'e bağlandı.

**Closeout-B2 sonucu:** hava durumu Core allowlist'ine eklendi; açık `pending_level` açık seviye isteğiyle geçersiz kılınıyor. Kalan regex ön kapıları ve `goal_executor` `work_modes` çağrısı PR9'da Live Brain girişine bağlanınca (caller-zero) taşınıp silinecek.

## 11. Cutover kuralları

- Shadow/dual-run varsa **tek effect owner Core** olmalı; legacy ve Brain aynı anda effect üretemez.
- Brain semantic understanding/proposal responsibility/ownership taşır; **authority taşımaz**.
- Brain candidate/reference state'i kopyalamaz; domain state'ten read-only snapshot alır.
- Brain semantic proposal üretir: canonical `capability_hint`, typed `arguments`, bounded `references`, `conversation_relation`, `temporal_need`, clarification/context proposal. **Capability/action validation-selection, permission, effect, execution, completion ve final dispatch authority Core'dadır.**
- Agent clarification yalnız “eksik alanı bildirir”; global semantic/reference proposal Brain'dedir; effect target identity ve gerçek action mapping Core/domain invariant tarafından doğrulanır.
- Domain parser, Core Brain `capability_hint` proposal'ını canonical capability/action mapping'ine doğruladıktan sonra kendi bounded input grammar'ını yorumlayabilir.
- `GoalExecutor`, permission/effect gates, worker evidence ve completion policy kaldırılmaz; **Core authority korunur**.
- Agents uzman worker'dır; kendi genel intent router'ı/reference resolver'ı/global completion authority'si olmaz.
- `WorkerResult` global completion kararı değildir; completion Core evidence/policy ile belirlenir.
- Candidate bulunması permission değildir; filesystem/path candidate'ı `nxapi.allowed`, symlink ve allowed-root execution guard'larını bypass edemez.
- Source timestamp yoksa Brain age/freshness uydurmaz; `ContextReference.recency` gerekirse `UNSURE` kalır. Generic clarification için source'ta olmayan TTL/expiry icat edilmez.
- History reset/session boundary ve bounded read korunur; legacy consumer 2h pencereleri yalnız parity davranışıdır, canonical global TTL değildir.
- Failure synthesis/recovery presentation structured failure kanıtını sunar; **blind retry yapmaz**.
- Advisor execution/permission authority taşımaz.
- Her legacy yol ancak replacement + parity + product invariant acceptance birlikte yeşil olduğunda, mümkün olan **ilk ilgili PR'da** silinir; PR10'u beklemek zorunda değildir.
- Brain Contracts canonicaldır; bu belge implementation'a yeni zorunlu schema field'ı eklemez.

## 12. Doğrulama beklentisi

Repo `modules.validation` içinde **Architecture Guard'ı zorunlu ilk grup olarak zaten çalıştırıyor**; Windows PR workflow'u da her PR'da `py -3.13 -X utf8 -m modules.validation` çalıştırıyor. Bu branch doküman-only olsa da repo workflow'u full validation'ı atlamıyor. Dolayısıyla draft PR CI kanıtı full validation + Architecture Guard sonucunu birlikte vermelidir.

Yerel/ajan ortamında repo checkout'u olmayan bir connector oturumunda komut sonucu uydurulmamalıdır. Bu rapor branch'i için doğrulama kaydı PR CI'dan alınmalı; ayrıca diff yalnız `docs/architecture/JARVIS_BRAIN_MIGRATION_MAP_V1.md` göstermelidir.