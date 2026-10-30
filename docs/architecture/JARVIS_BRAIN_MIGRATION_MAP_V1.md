# JARVIS BRAIN MIGRATION MAP V1

**Durum:** canonical migration denetimi — production davranışı değiştirmez.  
**Kaynak branch:** `origin/main` @ `344c1c7cc5290f63753908d1b7fe8b3d48c5a521`  
**Hedef:** tek genel Jarvis Brain; agents/workers uzman yürütücüler.  
**Bağımsızlık:** `gpt/brain-contracts-v1` branch'ine ve dosyalarına dokunulmamıştır.

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

Bu haritanın ana ayrımı şudur: **understanding authority tek Brain'de**, lifecycle/permission/completion authority **Core'da**, gerçek kayıt/evidence/safety doğrulaması **domain invariantlarında**, işin yapılması **worker/domain execution'da** kalır. Regex tek başına kötü sayılmamıştır; yalnız fast-gate için exact/bounded grammar, düşük false-positive, açık target/state, cross-domain seçim yapmama, determinism ve reference inference yapmama şartlarının altısı birlikte aranmıştır.

Denetim sonucu: **91 migration bulgusu**. KEEP=40, MOVE=36, RETIRE=13, NEEDS_DECISION=2.

## 2. Migration bulguları

| ID | Mevcut dosya/fonksiyon | Bugünkü rol | Caller | Sorun | Hedef sınıf | Hedef Brain parçası | Geçiş koşulu | Silme koşulu | Korunacak test/invariant |
|---|---|---|---|---|---|---|---|---|---|
| BRAIN-MIG-001 | engine_commands.py:handle → command_manager.engine_control | Jarvis kapat/uyku/uyan exact grammar | engine_commands.handle | Bounded protocol/control; domain seçmiyor | KEEP_FAST_GATE | DETERMINISTIC FAST GATE | Brain entry öncesi exact grammar listesi sabitlenir | Silinmez; yalnız ortak gate'e taşınabilir | engine control/source safety testleri |
| BRAIN-MIG-002 | job_front.py:wants/route | Çıplak devam/iptal ile açık task job seçimi | engine_commands.handle | Exact söz + gerçek open-state; eski task/goal ayrımını köprüler | KEEP_STATE_GATE | EXACT STATE GATE | GoalState/task state read-only görünümü sağlanır | Legacy task engine kalkarsa köprü sadeleşir | owner/open/stale/pending precedence |
| BRAIN-MIG-003 | goal_executor.py:handle + RESUME_COMMANDS | Hedef resume/approval/cancel protokolü | engine_commands.handle | Gerçek durable GoalState kontrolü; doğal intent değil | KEEP_STATE_GATE | EXACT STATE GATE | Canonical Brain pending/control envelope GoalState'i okuyabilmeli | Goal protocol aynı kalır; wrapper gerekmezse kaldırılır | stale job, approval, owner, cancel |
| BRAIN-MIG-004 | command_manager.py:awaiting_input/PENDING_INPUT_FIELDS | Session pending protokollerinin varlığını toplu görme | engine_commands.handle; job_front.route | State önceliği doğru; fakat alanlar dağınık | KEEP_STATE_GATE | EXACT STATE GATE | Alanlar typed PendingState görünümüne normalize edilir | Ham alan listesi yalnız tüm callerlara geçişten sonra kaldırılır | pending precedence |
| BRAIN-MIG-005 | app_actions.py:continue_voice confirmation branch | App action onayının owner+90s expiry ile tüketilmesi | command_manager.dispatch | Gerçek bekleyen onay; approval inference yapmıyor | KEEP_STATE_GATE | EXACT STATE GATE | PendingAction typed view Brain'e read-only sunulur | Legacy session shape kalkınca adapter silinir | owner/expiry/negative/positive token |
| BRAIN-MIG-006 | command_execution.py:pending_app/continue_app | Uygulama adayından sayı/ad ile seçim; 120s TTL | engine_commands.handle | Bounded candidate selection; farklı istek eski seçimi iptal ediyor | KEEP_STATE_GATE | EXACT STATE GATE | CandidateSelection state canonical gate'e görünür olur | Session adapter sonrası eski pocket silinir | TTL, exact candidate, no accidental approval |
| BRAIN-MIG-007 | engine_commands.py:_pending_photo branch | Telefondan gelen fotoğraf için 600s follow-up | engine_commands.handle | Gerçek pending artifact; fakat follow-up yorumlama legacy motorda | KEEP_STATE_GATE | EXACT STATE GATE | Pending artifact metadata ActiveContext'e read-only verilir | Legacy branch yalnız Brain aynı state'i tüketince kaldırılır | TTL, cancel, owner |
| BRAIN-MIG-008 | engine_commands.py:pending_organize branch | Klasör düzenleme onayı | engine_commands.handle | Gerçek pending effect confirmation | KEEP_STATE_GATE | EXACT STATE GATE | Canonical PendingEffect/permission hattına bağlanır | Legacy session confirmation wrapper sonrası | no mutation before approval |
| BRAIN-MIG-009 | engine_commands.py:pending_msg/_message_step | WhatsApp eksik alan + gönderim akışı | engine_commands.handle | Gerçek protocol state; intent authority burada kalmamalı | KEEP_STATE_GATE | EXACT STATE GATE | State Brain'e exact pending protocol olarak görünür | Messaging protocol adapter canonical olduktan sonra | recipient/message/approval invariants |
| BRAIN-MIG-010 | engine_commands.py:pending_confirm | Shutdown/close-app bekleyen onayı | engine_commands.handle; engine_intents.dispatch | Gerçek effect confirmation; iki producer var | KEEP_STATE_GATE | EXACT STATE GATE | Tek PendingEffect view | Producerlar Brain understanding'e taşınınca legacy field adapter silinir | no effect without confirmation |
| BRAIN-MIG-011 | engine_commands.py:pending_level | '70' sonrası ses/parlaklık seçimi | engine_commands.handle | Bounded iki adaylı clarification state | KEEP_STATE_GATE | EXACT STATE GATE | CandidateSelection{volume,brightness} olarak görünür | Brain canonical clarification aynı state'i ürettiğinde | number bound, explicit target |
| BRAIN-MIG-012 | engine_commands.py:pending_weather_location | Hava için şehir cevabı bekleme | engine_commands.handle; engine_tools._weather | Gerçek pending slot; ancak yeni cümlenin şehir sayılması broad | KEEP_STATE_GATE | EXACT STATE GATE | Pending slot + expected type/location Brain'e verilir | Canonical slot resolver devredeyken legacy branch silinir | cancel/no empty city |
| BRAIN-MIG-013 | visual_chat.py:pending_visual | Görsel kaynağı sohbet/dosya seçimi | command_manager.dispatch | Bounded iki seçenekli pending state | KEEP_STATE_GATE | EXACT STATE GATE | Pending source selection typed view | Brain aynı seçim state'ini üretince | only sohbet/dosya; no accidental consume |
| BRAIN-MIG-014 | learning.py:pending_facts | Onay bekleyen hafıza adayları | learning.handle; live prompt/app_actions | Durable approval state, memory truth değil | KEEP_STATE_GATE | EXACT STATE GATE | Brain yalnız read-only pending-memory status görür | Silinmez; storage domain-owned kalır | unapproved facts not memory |
| BRAIN-MIG-015 | hoca.py:lesson.pending | Bekleyen kontrol sorusu | hoca.check_question/grade | Domain protocol state; cevabı başka domaine taşımamalı | KEEP_STATE_GATE | EXACT STATE GATE | ActiveContext pending Hoca question view | Silinmez; Hoca domain-owned | pending question correctness |
| BRAIN-MIG-016 | watcher.py:_PENDING/run_pending | Saatlik kota nedeniyle bekleyen dosyalar | watcher.tick/handle | Gerçek operational pending queue | KEEP_STATE_GATE | EXACT STATE GATE | Brain read-only watcher pending count/ids görür | Silinmez; watcher domain-owned | hourly cap/no duplicate |
| BRAIN-MIG-017 | engine_commands.py:_split_steps/_run_steps | 'önce/sonra/ardından' multi-step parser | engine_commands.handle | Global sequence understanding Brain'den önce yapılıyor | MOVE_TO_UNDERSTANDING | UNDERSTANDING | UnderstandingResult sequence/ordering taşımalı | Yeni Brain sequence acceptance geçince legacy parser kaldırılır | order, pending/effect boundaries |
| BRAIN-MIG-018 | router.py:classify | Genel intent/domain/clarify/task kararı | engine_tools.route → engine_commands.handle | İkinci genel beyin; context+catalog+LLM+regex bir arada | MOVE_TO_UNDERSTANDING | UNDERSTANDING / CONFIDENCE | Brain contracts + parity corpus + fallback hazır | Tüm callers UnderstandingResult kullanınca router classifier emekli | routing corpus/product outcomes |
| BRAIN-MIG-019 | work_modes.py:classify/action_request | chat/do/spec üst seviye semantik karar | router.classify | Cross-domain doğal dil kararı; fast-gate şartlarını sağlamıyor | MOVE_TO_UNDERSTANDING | UNDERSTANDING | Brain intent relation alanı aynı ayrımı taşımalı | router legacy guard kalkınca | question vs execution |
| BRAIN-MIG-020 | freshness.py:fresh_request | Güncel dış veri ihtiyacı | router.classify; work_modes | Current-data ihtiyacı semantik; konu regex'i global intent seçiyor | MOVE_TO_UNDERSTANDING | UNDERSTANDING | UnderstandingResult.requires_current_data canonical olur | İki caller yeni field'a geçince | fresh vs static regression |
| BRAIN-MIG-021 | router.py:_definition_question/_open_only_request fast branches | Tanım ve open-only semantik shortcut | router.classify | Bounded görünse de cross-domain user outcome seçiyor | MOVE_TO_UNDERSTANDING | UNDERSTANDING | Brain confidence ile aynı sonuçlar | Router classifier cutover | definition/action regressions |
| BRAIN-MIG-022 | router.py → app_actions.reference_context | Komuta göre task/not/event/fact/rule/source kayıtlarını prompta toplar | router.classify | Global singleton profile + lexical candidate retrieval | MOVE_TO_CANDIDATE_BUILDER | CANDIDATE BUILDER | Owner-scoped providerlar candidate API verir | Brain candidate builder canlı olduğunda helper kaldırılır | owner isolation/no secret exposure |
| BRAIN-MIG-023 | engine_tools.py:route context assembly | recent_turns + last_command + pending_request JSON context | engine_commands.handle → runtime.route | Active context parçaları ad-hoc prompt stringi olarak birleşiyor | MOVE_TO_ACTIVE_CONTEXT | ACTIVE CONTEXT | Typed ActiveContext snapshot üretilecek | Router prompt context kaldırılınca | redaction/owner isolation |
| BRAIN-MIG-024 | session_state.py:SessionStore | Owner-scoped RAM conversation/pending state | engine_commands, command_manager, visual, app_actions | Doğru state sahibi; Brain ikinci kopya oluşturmamalı | MOVE_TO_ACTIVE_CONTEXT | ACTIVE CONTEXT | Read-only ActiveContext adapter SessionStore'dan okur | Store silinmez; yalnız tüketim adapteri değişir | owner ContextVar isolation |
| BRAIN-MIG-025 | session_state.py:last_command | Son başarılı routed komut | engine_tools.route | Referans sinyali ad-hoc ve TTL'siz | MOVE_TO_ACTIVE_CONTEXT | ACTIVE CONTEXT | Provenance+age ile view'a alınır | Legacy field caller kalmayınca | owner/reset |
| BRAIN-MIG-026 | session_state.py:pending_request | Clarify soru+orijinal komut pocket'ı | engine_intents.dispatch; engine_tools.route | Gerçek clarification continuation ama generic dict | KEEP_STATE_GATE | EXACT STATE GATE | Typed ClarificationPending(owner, question, original, expiry) | Canonical pending clarification sonrası | never infer approval |
| BRAIN-MIG-027 | chat_translation.py:resolve | 'bunu/son cevabı/önceki metni çevir' kaynak çözümü | command_manager.dispatch | Kendi 2 saatlik history resolver'ı; genel referans sistemiyle yarışıyor | MOVE_TO_REFERENCE_RESOLVER | REFERENCE RESOLVER | Brain resolver candidate/provenance ile translation source döndürür | Translation canonical resolver kullanınca | latest original user text; reset boundary |
| BRAIN-MIG-028 | chat_translation.py:_sources | RAM son çeviri kaynağı cache'i | chat_translation.remember/resolve | İkinci kısa süreli truth pocket; history ile fallback yarışıyor | RETIRE_AFTER_CUTOVER | ACTIVE CONTEXT | History/session source provenance yeterli olmalı | Resolver parity sonrası `_sources` kaldırılır | reset/no stale source |
| BRAIN-MIG-029 | chat_translation.py:_resets/chat_sessions.json | Yeni sohbet sonrası history kesme sınırı | chat_translation.recent; engine_voice._recent_turns | Durable session boundary; ikinci semantic memory olmamalı | MOVE_TO_ACTIVE_CONTEXT | ACTIVE CONTEXT | Conversation epoch/read-only boundary view | Domain storage kalabilir; consumers adaptere geçer | no pre-reset reference |
| BRAIN-MIG-030 | main_documents.py:_resolve_doc candidate enumeration | İzinli dosyalarda exact/stem aday toplama | engine_intents doc_*; engine_tools delegate | Candidate retrieval ve referans seçimi aynı fonksiyonda | MOVE_TO_CANDIDATE_BUILDER | CANDIDATE BUILDER | File candidate provider path/id/mtime/mine döndürür | Resolver ayrıldıktan sonra enumeration helper sadeleşir | allowed roots/owner |
| BRAIN-MIG-031 | main_documents.py:_resolve_doc reference selection | 'son dosya/yüklediğim/bu dosya' + exact/stem seçim | engine_intents doc_* | Genel reference inference domain içinde gömülü | MOVE_TO_REFERENCE_RESOLVER | REFERENCE RESOLVER | Brain file candidates üzerinde confidence/ambiguity uygular | No implicit file resolution caller kalınca | ambiguous must not mutate |
| BRAIN-MIG-032 | main_documents.py:_file_command global entry | Quoted path/follow-up doğal dilini router öncesi çalıştırır | engine_commands.handle | Canonical Brain'i bypass eden geniş execution entry | RETIRE_AFTER_CUTOVER | CORE entry adapter | Brain resolved file capability aynı işlemleri çağırır | Text/file UI parity acceptance sonrası pre-route call silinir | file permissions/output evidence |
| BRAIN-MIG-033 | main_documents.py/workbench.followup | 'şu sütunu ekle' gibi son tablo follow-up | _file_command | Domain-specific last artifact reference pocket | MOVE_TO_REFERENCE_RESOLVER | REFERENCE RESOLVER | Workbench artifact candidate ActiveContext'e çıkar | Brain resolver follow-up target verir | artifact identity/no stale edit |
| BRAIN-MIG-034 | app_actions.py:_check_reference | task/note/event/kb/goal/fact/rule id varlığını doğrular | app_actions.run/voice | Gerçek kayıt invariant'ı; understanding'e taşınmamalı | KEEP_DOMAIN_INVARIANT | SEMANTIC INVARIANTS / domain | Resolved reference id ile aynı validation sürer | Silinmez | wrong owner/nonexistent record |
| BRAIN-MIG-035 | nxapi.allowed + main_documents path checks | Dosya kök erişim sınırı | main_documents/file ops | Gerçek filesystem safety invariant | KEEP_DOMAIN_INVARIANT | SEMANTIC INVARIANTS / domain | Brain yalnız candidate id görür; path guard executionda kalır | Silinmez | allowed roots/symlink |
| BRAIN-MIG-036 | goal_tools._pc_owner | Telefon/başka foreground owner için fiziksel PC engeli | goal_tools.execute | Gerçek execution authority/invariant | KEEP_DOMAIN_INVARIANT | CORE/domain invariant | UnderstandingResult source/owner taşır | Silinmez | foreground owner/source |
| BRAIN-MIG-037 | task_agents._gate/runtime_execution_gate | Worker öncesi identity/state/permission/effect gate | task_agents worker loop | Gerçek güvenlik ve execution gate; Brain intent işi değil | KEEP_DOMAIN_INVARIANT | CORE | Resolved capability aynı gate'ten geçer | Silinmez | identity/approval/effect |
| BRAIN-MIG-038 | app_actions.py:run | Typed action validate + bridge/system execution | engine_intents; app_actions.voice | Capability execution; genel anlamaya karıştırılmamalı | KEEP_EXECUTION | CORE → WORKER | Brain action id/args üretir | Silinmez; compatibility wrapper sadeleşebilir | typed args/result |
| BRAIN-MIG-039 | engine_intents.py:dispatch execution arms | Resolved intent'i mevcut capability'lere bağlar | engine_commands.handle | Bugün router schema'sına bağlı compatibility dispatcher | KEEP_EXECUTION | CORE dispatch adapter | UnderstandingResult→capability mapping manifestle hizalanır | Legacy intent enum kalkınca adapter bölünebilir | same execution/result |
| BRAIN-MIG-040 | engine_intents.py:clarify arm | Generic pending_request üretir | router.classify result | Confidence/ambiguity kararı legacy router'a ait | RETIRE_AFTER_CUTOVER | CONFIDENCE / AMBIGUITY | Brain canonical clarification state üretir | No router clarify callers | no guessed target |
| BRAIN-MIG-041 | app_actions.py:continue_voice clarify reroute | Soru+cevabı string birleştirip router.classify tekrar çağırır | command_manager.dispatch | Recursive mini-brain; provenance kayboluyor | RETIRE_AFTER_CUTOVER | UNDERSTANDING / REFERENCE RESOLVER | Brain continuation input structured olmalı | Canonical clarification resume geçince | same owner/expiry |
| BRAIN-MIG-042 | engine_commands.py:typo recursive runtime.handle | Düzeltilmiş komutla tam pipeline'ı tekrar çağırır | engine_commands.handle | Recursive reroute; state/priority iki kez değerlendirilebilir | RETIRE_AFTER_CUTOVER | UNDERSTANDING preprocessing | Brain normalized_text + original_text taşır | No recursive handle needed | single request identity/no double effect |
| BRAIN-MIG-043 | engine_commands.py:app open regex | '<app> aç/başlat/çalıştır' direct open_app | engine_commands.handle | Cross-domain target semantics ve router bypass | MOVE_TO_UNDERSTANDING | UNDERSTANDING | Brain exact/bounded app-open grammarı fast gate kriteriyle yeniden kanıtlar ya da understanding'e alır | Parity sonrası legacy regex silinir | never open pronoun/unknown |
| BRAIN-MIG-044 | engine_commands.py:app close regex | '<app> kapat' direct pending_confirm | engine_commands.handle | Cross-domain target + destructive effect selection | MOVE_TO_UNDERSTANDING | UNDERSTANDING | Brain capability=app.close; confirmation Core | Parity sonrası legacy regex silinir | confirmation/no wrong app |
| BRAIN-MIG-045 | engine_commands.py:weather NL regex + _city_in | Hava intent ve şehir çıkarımı | engine_commands.handle | Weather için ayrı genel mini-router/reference extractor | MOVE_TO_UNDERSTANDING | UNDERSTANDING + REFERENCE RESOLVER | Brain weather intent + location candidate üretir | Router/fast duplicate kapandıktan sonra | airport false-positive/location |
| BRAIN-MIG-046 | engine_tools.py:_weather | Weather provider execution + city pref fallback | engine_intents; engine_commands | Execution doğru; pending slot üretimi canonical state'e bağlanmalı | KEEP_EXECUTION | CORE → weather worker | Resolved location/slot input alır | Silinmez | provider failure/no false success |
| BRAIN-MIG-047 | profile.data.prefs.city | Kayıtlı varsayılan şehir | engine_tools._weather | Domain-owned user preference; Brain copy etmemeli | MOVE_TO_ACTIVE_CONTEXT | ACTIVE CONTEXT | Read-only preference view | Storage kalır | owner scoped |
| BRAIN-MIG-048 | main_planner.py:_note_text/_note_fix | Not intent/body + 'son notu düzelt' follow-up parser | engine_tools planner/commands | Reference+intent inference organizer domaininde gömülü | MOVE_TO_UNDERSTANDING | UNDERSTANDING / REFERENCE RESOLVER | Brain note capability + target note id üretir | Legacy pre-route note parser silinir | don't mutate wrong note |
| BRAIN-MIG-049 | main_planner.py:_last_note 15dk pocket | Kısa düzeltmede son not zaman penceresi | _note_fix | Ephemeral reference context ayrı dict'te | MOVE_TO_ACTIVE_CONTEXT | ACTIVE CONTEXT | Last created note event/id+timestamp read-only view | Legacy dict caller kalmayınca | 15m scope/owner |
| BRAIN-MIG-050 | main_planner.py day/week/agenda regex | Takvim/plan doğal dil isteğini yakalar | engine_tools planner path | Global NL routing organizer implementationına gömülü | MOVE_TO_UNDERSTANDING | UNDERSTANDING | Brain organizer capability seçer | Pre-route parser kaldırılır | date semantics/calendar owner |
| BRAIN-MIG-051 | engine_tools.py:_mail_handle | Outlook/Gmail/meeting/draft doğal dil cascade | _extra_commands | Mail capability için ikinci router; router mail intent ile duplicate | RETIRE_AFTER_CUTOVER | UNDERSTANDING→CORE | Brain communication.mail capability seçer, domain parser yalnız args | No pre-Brain mail handle caller | provider/account invariants |
| BRAIN-MIG-052 | engine_tools.py:_extra_commands cascade | finance/plugin/handoff/folder/browser/tasks/kb/file/media/mail/notify zinciri | engine_commands macros/extra | En geniş legacy mini-router; ilk eşleşen kazanıyor | RETIRE_AFTER_CUTOVER | UNDERSTANDING→CORE | Her domain resolved capability adapterine bağlanır | Capability parity matrisi yeşil olunca cascade entry silinir | no behavior loss |
| BRAIN-MIG-053 | finance_alert_commands.matches/handle pre-Brain | Finans alarm NL girişi | engine_tools._extra_commands | Finance domain parser global entryde domain seçiyor | RETIRE_AFTER_CUTOVER | UNDERSTANDING→finance | Brain finance.alert intent seçer; domain validation kalır | Pre-Brain matches call kaldırılır | finance evidence/domain contract |
| BRAIN-MIG-054 | watcher.py:handle global entry | Klasör izleme NL girişini doğrudan yakalar | engine_commands.handle | Brain'den önce capability/domain seçiyor | RETIRE_AFTER_CUTOVER | UNDERSTANDING→watcher | Brain watcher capability seçer | No pre-Brain watcher caller | allowed folder/rule limit |
| BRAIN-MIG-055 | watcher.py:_WATCH/_WHEN/action parser | Seçilmiş watcher komutundan klasör/ext/action çıkarır | watcher.handle | Domain grammar; global router olmak zorunda değil | KEEP_EXECUTION | WORKER/domain parser | Brain watcher seçtikten sonra aynı parser input adapteri olabilir | Silinmez; sadece entry değişir | folder allowlist/limits |
| BRAIN-MIG-056 | watcher.py:scan/process/tick | Dosya tarama, stability, quota, execution | watcher loop | Gerçek worker execution | KEEP_EXECUTION | WORKER | Brain yalnız user-triggered control; background loop domain-owned | Silinmez | done/stability/hourly cap |
| BRAIN-MIG-057 | watcher.py durable rules + _STATE/_RECENT | İzleme rule truth + scan/runtime counters | watcher loop | Brain ikinci state kopyası oluşturmamalı | MOVE_TO_ACTIVE_CONTEXT | ACTIVE CONTEXT | Read-only watcher status provider | Storage/counters domain-owned kalır | owner/rule id |
| BRAIN-MIG-058 | hoca.py:context_for/active/current_step | Aktif ders/adım read-only context | engine_tools._study_intent/live prompt candidates | İyi domain-owned source; genel contextte standart değil | MOVE_TO_ACTIVE_CONTEXT | ACTIVE CONTEXT | Hoca provider typed lesson summary verir | Storage kalır | owner/course/step |
| BRAIN-MIG-059 | hoca.py:intent | Aktif Hoca içinde next/change/stay domain grammar | hoca.handle | Domain continuation parser; genel intent router olmamalı | KEEP_EXECUTION | WORKER/domain parser | Brain hoca domainini resolve eder, parser yalnız aktif lesson içinde | Silinmez | explicit next/change only |
| BRAIN-MIG-060 | study.last_topic fallback | Görsel/video için son ders konusu | engine_tools._study_intent | Ephemeral domain reference | MOVE_TO_ACTIVE_CONTEXT | ACTIVE CONTEXT | Study provider last_topic+age verir | Legacy direct lookup sonrası | owner/course |
| BRAIN-MIG-061 | visual_chat.py:_history_text | Son 40 history satırını görsel içerik yapar | visual_chat.handle | Ad-hoc context assembly; relevance/provenance yok | MOVE_TO_ACTIVE_CONTEXT | ACTIVE CONTEXT | Resolved conversation span/artifact Brain tarafından verilir | Visual handler raw history okumayınca | owner/reset |
| BRAIN-MIG-062 | session_state.py:last_visual | Retry için önceki visual request/content/kind | visual_chat.handle; main_documents | Kısa süreli artifact reference pocket | MOVE_TO_ACTIVE_CONTEXT | ACTIVE CONTEXT | Last visual artifact event/id + provenance | Legacy dict caller kalmayınca | owner/no cross-chat |
| BRAIN-MIG-063 | visual_commands.detect_type_by_keyword/model | Görsel türü semantik sınıflandırması | visual_chat; create_visual | Global sohbet girişinde mini intent sınıflandırıcı; model fallback ikinci brain çağrısı | MOVE_TO_UNDERSTANDING | UNDERSTANDING | Brain visual subtype alanı üretir | Visual entry canonical olunca detect yalnız explicit button fallback olabilir | visual subtype corpus |
| BRAIN-MIG-064 | visual_commands.create_visual | Prompt build + image generation + save | visual_chat/main_documents | Gerçek capability execution | KEEP_EXECUTION | WORKER | Resolved subtype/content alır | Silinmez | output path/image failure |
| BRAIN-MIG-065 | learning.py:rules/facts/pending + prompts | Behavior/memory domain-owned durable state | profile/live/chat system prompt | Context source; authority olmamalı | MOVE_TO_ACTIVE_CONTEXT | ACTIVE CONTEXT | Memory candidate provider relevance+provenance ile read-only | Storage kalır; direct prompt injection kalkar | rules cannot override permission/core |
| BRAIN-MIG-066 | learning.py:query_scopes/rule_scope | Komuta göre ilgili davranış kuralı seçimi | rules_prompt | Relevance/candidate selection Brain dışında regex mini-selector | MOVE_TO_CANDIDATE_BUILDER | CANDIDATE BUILDER | Memory provider candidates; Brain relevance gate | Direct rules_prompt query filtering kalkınca | global rules + scoped rules |
| BRAIN-MIG-067 | goal_executor.py:latest/is_open/status | Durable GoalState truth ve open/stale görünümü | engine_commands/job_front/queue | Canonical execution state; Brain ikinci lifecycle yaratmamalı | KEEP_STATE_GATE | EXACT STATE GATE | Read-only GoalState summary ActiveContext'e eklenir | Silinmez | CAS/owner/stale |
| BRAIN-MIG-068 | goal_executor.py:_planner/_loop/run | Durable goal planning/execution | engine_intents task; explicit goal | Core execution/planning; understanding brain ile karıştırılmamalı | KEEP_EXECUTION | CORE | UnderstandingResult goal/capabilities ile giriş yapar | Silinmez; compatibility request parser sadeleşir | permission/evidence/completion |
| BRAIN-MIG-069 | completion_policy.py + goal_executor completion checks | Global completion evidence policy | goal_executor | Canonical Core completion; worker/agent'e taşınmamalı | KEEP_EXECUTION | CORE | Brain yalnız intent/result verir; completion Core'da | Silinmez | no false done |
| BRAIN-MIG-070 | task_agents.py:handle natural-language admin entry | 'görev akışı/devam/iptal/geçmiş' legacy entry | command_manager.dispatch/job_front | İkinci task front door ve genel NL interception | RETIRE_AFTER_CUTOVER | CORE entry | Canonical Brain/GoalState task continuation kapsar | Legacy task front door callers sıfırlanınca | existing job recovery |
| BRAIN-MIG-071 | task_agents.py durable DAG/worker/_gate | Legacy durable specialist execution | task_agents.handle/specialist bridge | Gerçek execution/evidence; cutover planı dışında aniden silinemez | KEEP_EXECUTION | AGENTS / WORKERS | Core compatibility adapter altında kalır | GoalState canonical replacement + data migration kanıtı sonrası ayrıca karar | recovery/evidence/owner |
| BRAIN-MIG-072 | task_agents.py:recent | Son task job seçimi | job_front | Durable task state lookup; active contextte read-only olmalı | MOVE_TO_ACTIVE_CONTEXT | ACTIVE CONTEXT | Legacy task summary provider | Task engine emekli olunca | owner/stale |
| BRAIN-MIG-073 | advisory_router.py:_mode | decision/critique/guidance isteğini doğal dilden seçer | engine_tools._sys_prompt; finalize | Genel NL interpretation; Brain ile aynı resolved context'i kullanmalı | MOVE_TO_UNDERSTANDING | UNDERSTANDING | UnderstandingResult.advisor_mode | Legacy requested() regex entry kalkınca | explicit advisory request |
| BRAIN-MIG-074 | advisory_router.py:finalize + advisor renderers | Resolved advisory output schema/render | chat fallback | Execution/permission authority yok; response shaping | KEEP_EXECUTION | Advisor layer after Understanding | Brain resolved context + chat result ile beslenir | Silinmez | no dispatch/no permission |
| BRAIN-MIG-075 | proactive_advisor.SuggestionPolicy | Suggestion enable/filter/render | advisory_router | İkinci Core değil; yalnız advisory output | KEEP_EXECUTION | ADVISOR | Resolved context ile suggestion üretir | Silinmez | no execution authority |
| BRAIN-MIG-076 | engine_voice.py:_live_prompt | Live için goals/facts/rules/pending/history/STT context kurar | engine_loop → live.start | Text Brain'den ayrı context snapshot; drift riski | MOVE_TO_ACTIVE_CONTEXT | ACTIVE CONTEXT | Live aynı ActiveContext serializer'ı kullanır | Private live prompt context assembly kaldırılır | owner/redaction/reset |
| BRAIN-MIG-077 | engine_voice.py:_context_prompt | Live modele son 2 saati verip 'onu/az önceki' çözmesini söyler | _live_prompt | Ayrı reference resolver fiilen Live modelin içinde | MOVE_TO_REFERENCE_RESOLVER | REFERENCE RESOLVER | Live utterance Brain resolver'dan UnderstandingResult alır | Live model kendi pronoun resolution authority'sini bırakınca | text/live parity |
| BRAIN-MIG-078 | live_tool_runner.py special direct tools | muzik_cal/_play_music, handoff, mishearing, voice change direct yolları | Live function-call model | Normal Brain/router/Core'u kısmen bypass ediyor | RETIRE_AFTER_CUTOVER | Canonical Brain entry | Live function call önce Brain understanding/result; execution aynı worker'a | Live parity acceptance sonrası direct semantic dispatch kaldırılır | permission/source parity |
| BRAIN-MIG-079 | engine_voice.py:_live_command | Live `komut` toolunu normal runtime.handle'a köprüler | live_tool_runner/live session | İyi compatibility entry; request identity/source korunuyor | KEEP_EXECUTION | Brain entry adapter | runtime.handle içinde Brain canonical olur | Live tool surface sadeleşince adapter kalabilir | same request owner/source |
| BRAIN-MIG-080 | engine_queue.py:submit command queue | Text/Web/Phone komutlarını aynı engine eventine taşır | UI/phone server | Transport execution; intent çözmüyor | KEEP_EXECUTION | Brain entry transport | Event consumer Brain entry çağırır | Silinmez | request id/owner/cancel |
| BRAIN-MIG-081 | engine_queue.py:direct goal status branch | 'hedef durumu/işin durumu/hedef ayrıntıları' queue içinde render | UI/phone submit | Canonical Brain/engine handle'ı bypass eden transport-level intent | RETIRE_AFTER_CUTOVER | EXACT STATE GATE | Exact state query Brain State Gate'e taşınır | All transports same Brain entry olunca | same status text/owner |
| BRAIN-MIG-082 | engine_queue.py:submit_audio STT→command | Phone audio transport | phone server/engine loop | Transport; command path sonunda aynı handle'a gitmeli | KEEP_EXECUTION | Brain entry transport | STT text canonical Brain entry | Silinmez | owner/rid |
| BRAIN-MIG-083 | engine_commands.py bare objectless verb pending_request | 'aç/kapat/sil/gönder' için clarification | engine_commands.handle | Ambiguity detection legacy regex'te, Brain confidence'dan önce | MOVE_TO_UNDERSTANDING | CONFIDENCE / AMBIGUITY | Brain unresolved target => typed clarification | Parity sonrası regex silinir | never guess target |
| BRAIN-MIG-084 | engine_commands.py bare number pending_level | '70 yap' → volume/brightness clarification | engine_commands.handle | State sonucu doğru ama ambiguity detector global legacy | MOVE_TO_UNDERSTANDING | CONFIDENCE / AMBIGUITY | Brain candidate set + confidence canonical state üretir | Detector silinir; pending state korunur | bounded 0-100 |
| BRAIN-MIG-085 | command_manager.py → developer.handle | Geliştirme modu aktifken genel komutları kendi turn/memory/tool loop'una alır | command_manager.dispatch | Uzman agent kendi sohbet bağlamı ve genel continuation yorumunu taşıyor; aktif mod sınırı nedeniyle migration şekli sözleşme kararı ister | NEEDS_DECISION | UNDERSTANDING / AGENT boundary | Brain Contracts PR agent-session input sözleşmesini netleştirir | Brain resolved intent developer worker'a devredince global interception kaldırılır | auth/draft/test/apply invariants |
| BRAIN-MIG-086 | developer.py:state.turns/state.memory/_old_turns | Uzman-local conversation ve memory | developer._turn | Genel chat memory gibi kullanılma riski; fakat proje-local worker scratchpad olabilir | MOVE_TO_ACTIVE_CONTEXT | ACTIVE CONTEXT | Yalnız developer task-scoped context provider olarak expose edilir; global truth yapılmaz | Global command reference için kullanım bitince | owner/auth/project scope |
| BRAIN-MIG-087 | developer.py:handle exact draft/apply/test commands | Taslak göster/test/apply/undo gibi bounded domain protocol | command_manager.dispatch | Aktif developer modunda hedef açık, grammar bounded | KEEP_STATE_GATE | EXACT STATE GATE | Active developer session state + exact protocol Brain gate'e görünür | Silinmez; entry adapter sadeleşebilir | password/auth, no auto-apply, fresh test |
| BRAIN-MIG-088 | command_manager.py → desktop_agent.handle | PC görevi doğal dilini pre-Brain yakalar | command_manager.dispatch | Agent global intent/domain interception yapıyor | RETIRE_AFTER_CUTOVER | UNDERSTANDING→CORE | Brain desktop_task resolve eder; GoalExecutor üzerinden canonical execution | No pre-Brain desktop_agent.handle caller | Core prepare/approval/evidence |
| BRAIN-MIG-089 | desktop_agent.py:validate/_permission_decision/_perform | UIA target/effect/permission/evidence uygulaması | goal_tools/task workers/legacy desktop entry | Gerçek domain invariant + effect execution; Brain'e taşınmamalı | KEEP_DOMAIN_INVARIANT | SEMANTIC INVARIANTS / WORKER | Resolved desktop goal mevcut gate'e gelir | Silinmez | target identity, secret/outbound block, verification |
| BRAIN-MIG-090 | smart_router.py:task_type | Prompttan code/analysis/chat/vision provider sınıfı seçimi | smart_router.run | Bu user intent router değil provider capability sınıfı; Brain migration kapsamındaki yeri tam contracta bağlı | NEEDS_DECISION | post-Understanding provider routing | Brain UnderstandingResult task kind sağlayabilirse duplicate kaldır; yoksa provider-local classifier kalır | Contracts sonrası tek owner belirlenir | zero-cost/privacy/provider evidence |
| BRAIN-MIG-091 | smart_router.handle / usage_meter.handle / system_doctor.handle exact admin commands | Router/kota/tanı config/status exact komutları | command_manager.dispatch | Bounded admin grammar; target açık ve cross-domain inference yok | KEEP_FAST_GATE | DETERMINISTIC FAST GATE | Exact registry altında testli kalır | Silinmez; ortak fast gate'e taşınabilir | no paid enable without evidence; exact commands |

## 3. Duplicate execution path matrisi

Buradaki “duplicate”, aynı kullanıcı capability'sine birden fazla **entry/selection** yolu olduğu anlamındadır; alttaki gerçek worker'ın paylaşılması tek başına duplicate sayılmamıştır.

| Capability | Yol A | Yol B / ek yol | Hangisi canonical kalmalı | Diğeri ne zaman silinir |
|---|---|---|---|---|
| weather | engine_commands weather regex → _weather | router.classify(weather) → engine_intents → _weather | Brain understanding → tek weather execution adapter | Legacy pre-route regex ve router intent duplicate parity sonrası |
| finance | engine_tools._extra_commands → finance_alert_commands | router freshness/task → goal_executor finance/data | Brain finance intent; alarm domain parser yalnız resolved finance.alert altında | Pre-Brain finance matches kaldırılınca |
| media | engine_commands/media legacy yolları + engine_tools.media.handle | router intent=media → engine_intents; Live muzik_cal direct | Brain media capability → aynı execution/effect gate | Direct Live/legacy media dispatch parity sonrası |
| volume/brightness | engine_commands pending_level/direct regex | router volume/brightness → engine_intents | Brain resolved pc.setting capability; pending state State Gate | Legacy regex paths parity sonrası |
| app open/close | engine_commands direct app regex | router open_app/close_app → engine_intents/app_actions | Brain app capability → command_execution/app action | Direct pre-route regex sonrası |
| file/document | engine_commands → main_documents._file_command | router doc_* → engine_intents → _resolve_doc | Brain candidate+resolver → file execution adapter | _file_command global entry ve embedded resolver sonrası |
| note/calendar | main_planner pre-route regex/helpers | router note/app_action event_* | Brain understanding/reference → profile/calendar execution | Legacy planner intent parser sonrası |
| mail | engine_tools._mail_handle/Google/Outlook handles | router mail → engine_intents; task_agents account worker | Brain communication.mail; Core mode fast vs durable seçer | Pre-Brain mail cascade sonrası |
| research | freshness/work_modes → router task | explicit goal/task → goal_executor; task_agents research legacy | Brain requires_current_data → Core research capability | Legacy task_agents front door ve freshness route sonrası |
| visual | visual_chat keyword/pending → visual_commands | main_documents visualize; Live/model tools where applicable | Brain visual intent/subtype; source pending State Gate | Global keyword detector entry after parity |
| translation | command_manager → chat_translation.resolve | router translate/doc_translate → engine_intents/main_documents | Brain resolver source + translation capability | chat_translation resolver/_sources sonrası |
| desktop | command_manager → desktop_agent.handle | router desktop_task → goal_executor → desktop worker | Brain desktop_task → Core/GoalExecutor canonical | Direct agent entry sonrası |
| developer | command_manager → developer.handle active-mode interception | goal_executor coder/task_agents coder paths | Brain developer intent → authenticated developer worker/Core mode | Agent-session contract sonrası |
| handoff | engine_tools._extra_commands → handoff.handle | router handoff → engine_intents; Live gorev_ekle direct | Brain handoff capability → one execution path | Pre-Brain + Live direct semantic dispatch sonrası |

**Toplam duplicate capability ailesi: 14.**

## 4. Canonical Active Context Sources

Kural: Brain yeni bir truth-store oluşturmaz. Domain-owned state korunur ve Brain'e yalnız **read-only ActiveContext view** verilir.

| Context kaynağı | State sahibi / saklama | Owner-scoped | TTL / yaşam | Brain read-only okuyabilir mi? | Yeni state'e kopyalansın mı? |
|---|---|---|---|---|---|
| SessionStore pending fields | SessionStore / RAM | evet | alan bazlı; bazıları TTL taşıyor | evet | hayır; read-only view |
| SessionStore last_command/last_doc/last_visual | SessionStore / RAM | evet | çoğunda explicit TTL yok | evet | hayır; provenance+age view |
| Conversation history | history store / durable | evet | query ile 2h/limit gibi view sınırları | evet | hayır |
| chat session reset epoch | chat_translation chat_sessions.json / durable | evet | reset boundary | evet | hayır |
| GoalState/latest job | goal_executor store / durable | evet | STALE_SECONDS semantics | evet | hayır |
| Legacy task DAG/latest | task_agents store / durable | evet | job semantics | evet | hayır; compatibility view |
| Profile tasks/notes/events/goals/facts/rules/prefs | profile data / durable | evet | domain-dependent | evet | hayır |
| Hoca lesson/current step/pending question | profile.data[hoca] / durable | evet | lesson lifecycle | evet | hayır |
| Study last topic/docs | study state / durable/profile-backed | evet | domain-specific | evet | hayır |
| Watcher rules | DATA_DIR/izleme / durable | evet | rule lifecycle | evet | hayır |
| Watcher runtime counters/pending quota | watcher RAM | evet | 1h recent window / process lifetime | evet | hayır |
| Workbench last artifact/job | workbench domain state | evet | implementation-specific recent state | evet | hayır |
| Developer turns/memory/draft state | developer store / durable | evet | developer-session scope | evet, yalnız task-scoped | hayır |
| Provider/router health/evidence | smart_router owner state + RAM | evet | evidence TTL/cooldown | gerektiğinde | hayır |
| Current transport source/request id | EngineContext / request state RAM | evet | request lifetime | evet | hayır |
| Foreground PC owner | EngineContext pc_profile / runtime | evet | runtime lifetime | evet | hayır |

**Toplam canonical Active Context source ailesi: 16.**

### Legacy context pockets

Gerçek konuşma/intent/reference bağlamı taşıdığı doğrulanan cepler:

- `SessionState.last_command`, `last_doc`, `last_visual`, `pending_request`, `pending_visual`, `pending_app` ve diğer `pending_*` alanları.
- `chat_translation._sources` ve durable reset epoch'u.
- `main_planner._last_note`.
- `workbench` son artifact/job state'i.
- `study.last_topic` / Hoca current step.
- developer `state.turns` / `state.memory`.
- Live `_recent_user` ve `_context_prompt` history görünümü.
- watcher `_PENDING` gerçek operational state'tir; `_RECENT` kota penceresidir. Bunlar global sohbet hafızası değildir.
- `smart_router._LAST`/health benzeri provider operational kayıtları conversation reference değildir; Brain memory olarak taşınmamalıdır.

İsim eşleştiği halde bağlam bulgusu sayılmayan örnekler: performans ölçümündeki `last_*`, audio timing, cursor/update counters, UI widget timestamps. Bunlar Brain context'i değildir.

## 5. Test sınıflandırması

### PRODUCT INVARIANT — korunacak

Aşağıdaki test davranışları implementation değişse bile korunmalıdır:

- owner/request identity eşleşmesi; başka kullanıcının GoalState, task, note, file, developer veya PC state'ine erişmeme.
- stale approval/pending selection tüketmeme; TTL ve cancel semantics.
- ambiguous reference ile mutate/send/open/close yapmama.
- nonexistent record/path/candidate üzerinde effect üretmeme.
- `nxapi.allowed`, symlink/path sınırları ve desktop target identity.
- permission/effect policy olmadan outbound/destructive action çalıştırmama.
- worker sonucunu global completion saymama; completion evidence/Core policy.
- Live/Phone source nedeniyle fiziksel PC owner invariantını bypass etmeme.
- memory/rules'ın permission, Domain Invariant, Decision Authority veya Effect Policy'yi geçersiz kılamaması.
- current-data/research isteğinin stale/static cevap yoluna sessizce düşmemesi.
- clarification'da farklı bir yeni isteğin eski pending işlemi yanlışlıkla onaylamaması.
- document/reference resolution'da owner ve gerçek artifact identity'nin korunması.

### LEGACY IMPLEMENTATION TEST — migration sırasında yeniden yazılabilir

Eski regex sırası, belirli helper çağrısı, `router.classify` intent enum'u, `engine_commands.handle` içindeki branch sırası veya tam prompt string'ini kilitleyen testler product invariant değildir. Bunlar yeni Brain'de aynı kullanıcı outcome'unu doğrulayacak şekilde güncellenmelidir.

`tests/data/yonlendirme_cumleleri.json` **silinmemeli**. İçindeki gerçek kullanım cümleleri regression corpus olarak korunmalıdır: chat-vs-action, weather, app open/close, volume/brightness/media, mail, note/handoff, translation, doc convert, finance/current-data, research, ambiguous pronouns ve multi-step örnekleri yeni Brain acceptance setine taşınmalıdır. Ancak `model`/`beklenen` alanları yeni Brain için “regex kural kitabı” değildir; corpus outcome/confidence/capability regression verisidir. `bilinen_hata`, `bekletilmis`, `tartismali` gibi metadata da overfit ölçümü için korunabilir.

## 6. Text / Voice / Live / Phone Brain Entry Matrix

| Giriş | Bugün gördüğü history/context | Router bypass? | Kendi tool/intent çözümü? | Canonical Brain bağlantısı |
|---|---|---|---|---|
| Text/Web | history + SessionStore + profile; router context son 2 saatten 6 turn | genelde hayır; fakat queue direct goal-status bypass var | router + çok sayıda pre-router handler | engine_queue/event → tek Brain entry; state query State Gate |
| Voice (non-Live STT) | aynı SessionStore/history; source=ses | hayır; normal handle'a girer | normal engine router | STT text doğrudan aynı Brain entry |
| Live | _live_prompt profile/facts/rules/pending + son 2 saat 12 turn; Live-local recent_user | evet, bazı özel tools normal handle'ı bypass ediyor | Live model kendi tool selection + context/reference çözümü | her utterance/tool intent canonical Brain UnderstandingResult; Live yalnız transport/voice surface |
| Phone text | owner/request id + normal session/history | queue'daki goal-status exact branch bypass ediyor | sonrasında normal handle | queue yalnız transport; exact status State Gate dahil Brain entry |
| Phone audio | STT sonrası phone owner/rid + normal session | STT sonrası normal command path | normal engine router | STT result aynı Brain entry |
| Phone photo | pending photo + question; session/owner | foto event/pending branch özel | photo follow-up parser engine_commands | artifact state State Gate + Brain resolver; vision execution worker |

Önemli parity sonucu: non-Live ses ve normal text aynı `runtime.handle()` hattına yakınken, **Live tam eşit değildir**. `_live_prompt` ayrı context/reference talimatı kurar ve `live_tool_runner` bazı özel araçları normal handler'dan bağımsız çalıştırır. Phone text de queue katmanındaki direct goal-status branch nedeniyle küçük bir bypass taşır.

## 7. Advisor katmanı

`advisory_router.py` kodu açıkça work dispatch, GoalState write, permission check veya worker execution yapmıyor. Bu nedenle decision/critique/guidance/proactive mekanizmaları ayrı bir genel Core/Brain olarak değerlendirilmemelidir.

Migration kararı:

- `advisory_router._mode` ve `decision_advisor.requested` / `critique_advisor.requested` / `guidance_advisor.requested` doğal dil seçimi **MOVE_TO_UNDERSTANDING**.
- schema validation/render/finalize ve proactive suggestion policy **Advisor output layer** olarak kalabilir.
- Advisor aynı `UnderstandingResult` ve resolved context'i tüketmeli; kendi history/reference resolver'ını kurmamalı.
- Advisor'a execution, permission, target selection veya global completion authority verilmemeli.

## 8. En tehlikeli 10 legacy yol

1. engine_tools._extra_commands — çok sayıda domaini ilk eşleşen kazanır mantığıyla Brain'den önce seçiyor.
2. router.classify — regex + model + app reference context + freshness ile ikinci genel beyin.
3. command_manager.dispatch — visual/task/developer/desktop/translation/Hoca gibi birçok pre-Brain front door.
4. engine_commands.handle içindeki app/weather/note/file/sequence legacy yolları — canonical understanding öncesi davranış seçiyor.
5. app_actions.continue_voice clarify — string birleştirip router.classify recursive çağrısı yapıyor.
6. engine_commands typo recursive runtime.handle — aynı request içinde tam pipeline'ı yeniden değerlendiriyor.
7. main_documents._file_command/_resolve_doc — execution, candidate retrieval ve 'bu/son dosya' reference inference aynı yerde.
8. chat_translation.resolve + _sources — ayrı 2 saatlik reference resolver ve RAM fallback truth pocket.
9. Live special tools/live prompt — ayrı context/reference/tool-selection ile text parity'yi bozuyor.
10. developer.handle / desktop_agent.handle pre-Brain interception — uzman agentların genel komut girişini sahiplenebildiği yollar.

## 9. İlk silinebilecek 5 parça

Canonical replacement ve parity testleri geldikten sonra risk sırasına göre:

1. chat_translation._sources RAM cache — canonical resolver history/provenance parity sonrası.
2. engine_queue direct goal-status render bypass — State Gate canonical entry geldiğinde.
3. app_actions clarification re-route (combined string → router.classify) — structured clarification resume geldiğinde.
4. engine_commands typo recursive handle — normalized/original text Brain inputunda taşındığında.
5. router içindeki app_actions.reference_context prompt helper — Candidate Builder providerları devreye girince.

## 10. Önerilen Migration Sırası

Mevcut yaklaşık 10 PR yaklaşımı korunabilir; ancak **Active Context ve Candidate Builder, Understanding cutover'dan önce** gelmeli. Aksi halde yeni Brain eski prompt-string context ceplerini yeniden kullanarak ikinci truth-source riskini taşır.

| PR | Girecek yollar | Çıkacak legacy yollar | Önkoşul | Acceptance |
|---|---|---|---|---|
| PR 1 — brain-contracts-v1 (başka ajan) | Brain contracts/types | yok | mevcut | Contracts tests; bu rapor branch'inden bağımsız |
| PR 2 — brain-active-context-v1 | SessionStore/history/profile/Hoca/GoalState read-only providers | ad-hoc prompt context assembly'e paralel adapter | PR1 | owner isolation; no copied truth; text/live same snapshot fields |
| PR 3 — brain-candidates-v1 | file/profile/memory candidate providers | app_actions.reference_context retrieval side; _resolve_doc enumeration side | PR2 | candidate provenance/owner/allowed roots |
| PR 4 — brain-reference-resolver-v1 | translation/file/note/visual/workbench references | chat_translation.resolve authority; embedded 'bu/son' resolvers | PR2-3 | ambiguous reference no action; reset/TTL/provenance |
| PR 5 — brain-understanding-v1 | router/work_modes/freshness/sequence/advisor-mode outputs | legacy classifier shadow-mode only | PR1-4 | yonlendirme corpus + ambiguity/current-data/sequence parity |
| PR 6 — brain-state-fast-gates-v1 | Exact State Gate + proven deterministic fast registry | scattered pending/engine_control/admin exact gate checks | PR2, PR5 | pending precedence, owner/TTL; every fast rule six criteria |
| PR 7 — brain-core-entry-text-v1 | text/web/phone command transport → Brain result → Core | pre-router extra/file/watcher/mail/app/note entry paths begin shadow-disable | PR3-6 | duplicate matrix text parity; no prod capability loss |
| PR 8 — brain-live-parity-v1 | Voice/Live/Phone same Brain entry/context/resolver | Live private reference authority and special semantic direct dispatch | PR7 | text/voice/live/phone same intent/reference outcome; source permissions preserved |
| PR 9 — brain-legacy-retirement-v1 | canonical Brain only for migrated paths | router.classify legacy authority, extra cascade, translation cache, recursive reroutes, direct agent front doors | PR7-8 | full regression + product invariants; no duplicate entry in matrix |
| PR 10 — brain-cutover-acceptance-v1 | cleanup/docs/architecture guards/test reclassification | remaining shadow flags/legacy implementation tests | PR9 | full validation; live/text parity; duplicate-path count canonicalized; no second truth source |

### PR 2-10 için önerilen düzeltme

Evet: sıralamada iki düzeltme öneriyorum.

1. Active Context + Candidate Builder, Reference Resolver ve Understanding'den önce kurulmalı.
2. Text cutover ile Live parity aynı PR'a sıkıştırılmamalı; önce text/web/phone command entry stabil hale gelmeli, sonra Live özel tool bypass'ları kaldırılmalı.

Yeni faz/özellik önerilmiyor; bu yalnız mevcut Brain migration işinin bağımlılık sırasıdır.

## 11. Cutover kuralları

- Shadow/dual-run varsa **tek effect owner Core** olmalı; legacy ve Brain aynı anda effect üretemez.
- Brain candidate/reference state'i kopyalamaz; domain state'ten read-only snapshot alır.
- Agent clarification yalnız “eksik alanı bildirir”; global target/intent authority Brain'dedir.
- Domain parser, Brain domain/capability seçtikten sonra kendi input grammar'ını yorumlayabilir.
- `GoalExecutor`, permission/effect gates, worker evidence ve completion policy kaldırılmaz.
- Her legacy yol ancak replacement + parity + product invariant acceptance birlikte yeşil olduğunda silinir.
- Brain Contracts branch'i bağımsızdır; bu belge contracts implementation'ına dosya bağımlılığı eklemez.

## 12. Doğrulama beklentisi

Repo `modules.validation` içinde **Architecture Guard'ı zorunlu ilk grup olarak zaten çalıştırıyor**; Windows PR workflow'u da her PR'da `py -3.13 -X utf8 -m modules.validation` çalıştırıyor. Bu branch doküman-only olsa da repo workflow'u full validation'ı atlamıyor. Dolayısıyla draft PR CI kanıtı full validation + Architecture Guard sonucunu birlikte vermelidir.

Yerel/ajan ortamında repo checkout'u olmayan bir connector oturumunda komut sonucu uydurulmamalıdır. Bu rapor branch'i için doğrulama kaydı PR CI'dan alınmalı; ayrıca diff yalnız `docs/architecture/JARVIS_BRAIN_MIGRATION_MAP_V1.md` göstermelidir.