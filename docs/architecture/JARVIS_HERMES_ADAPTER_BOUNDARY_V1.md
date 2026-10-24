# Jarvis ↔ Hermes-benzeri Dış Agent/Skill Adapter Sınırı v1

**Durum:** Mimari sözleşme taslağı — bağlayıcı adapter authority sınırı.
**Kapsam:** Bu belge yalnız dış agent/skill runtime'larının (Hermes-benzeri
`NousResearch/hermes-agent` sınıfı sistemler dahil) Jarvis'e ileride
bağlanacağı adapter sınırını tanımlar. Hermes'in clone/install/import'u,
lisans/Python/Windows/CUA benchmark ayrıntısı, worker kodu, GoalState/
Reducer/Permission/Effect değişikliği, CI/watcher/AGENTS.md/test değişikliği
ve yeni planner veya ikinci execution engine bu belgenin kapsamı dışındadır.
Bu belge yalnız kod incelemesiyle doğrulanmış mevcut mimari kurallara dayanır;
henüz uygulanmamış hiçbir mekanizma varsayılmaz.

**Kaynak doğrulama:** Bu belgedeki her sınır aşağıdaki kod ve mimari
belgelerden okunarak doğrulanmıştır:

- `docs/architecture/JARVIS_EXECUTION_ARCHITECTURE_V1.md` (Ana karar, §3, §5.1,
  §6, §10–§13, §15, §31 değişmez kurallar)
- `docs/architecture/JARVIS_CAPABILITY_INTAKE_V1.md` ("Değişmez Core sınırı",
  Hermes değerlendirmesi — ilk dalga karar listesindeki #10 "Hermes browser
  provider" = `ERTELENMİŞ`, #16 "Delegation/sub-agent" = `ERTELENMİŞ`)
- `docs/architecture/GOALSTATE_REDUCER_V1.md` (reducer'ın tek mantıksal yazıcı
  olma sözleşmesi)
- `modules/goal_state.py` (canonical `goal_state.v1` şeması, sürüm/terminal
  kuralları)
- `modules/core_state_reducer.py` (`apply`, `StaleStateError`,
  `TerminalStateError`, `expected_version` denetimi)
- `modules/goal_state_store.py` (`compare_and_swap`, kimlik ve audit geçmişi
  korumaları)
- `modules/worker_result.py` (`worker_result.v1` şeması, `_FENCE` alanları,
  `FenceError`, `accept()`)
- `modules/worker_result_commit.py` (kabul edilmiş WorkerResult'un yalnız
  reducer + CAS üzerinden evidence olarak yazılması)
- `modules/capability_manifest.py` (manifest alan kümesi `_FIELDS`, statik
  metadata/binding ayrımı, "This is a compatibility adapter, not a dispatcher
  or a second tool catalog" docstring'i)
- `modules/capability_hub.py` (`public_binding`/`read` — binding/callable
  detayının manifest JSON'u dışında, ayrı `service_store` kaydında tutulduğu
  kanıtı)
- `modules/effect_journal.py` (append-only effect intent/receipt sözleşmesi,
  "never executes, retries or reconciles effects" docstring'i)
- `modules/permission_gate.py` (`CLASSES`, tek izin otoritesi)
- `modules/specialist_orchestrator.py` ("This legacy convenience path has no
  durable identity, DecisionContext, WorkerResult fence or effect journal. It
  must never become a second executor" — dahili delegasyon için bile geçerli
  olan ikinci-yürütücü yasağının emsali)

## 1. Amaç ve çerçeve

Jarvis'in hedef yürütme omurgası tektir:

```text
Jarvis Core
→ GoalState + DecisionContext
→ Domain Invariant → Decision Authority → Permission Gate → Effect Policy
→ Worker + Capability
→ WorkerResult + Evidence + Effect
→ Core State Reducer (CAS)
→ Completion Policy
→ Cevap / Teslim
```

(`docs/architecture/JARVIS_EXECUTION_ARCHITECTURE_V1.md` §1, §32)

Hermes-benzeri bir dış agent/skill runtime'ı bu omurgaya yeni bir karar
otoritesi olarak eklenemez. `JARVIS_CAPABILITY_INTAKE_V1.md`'nin "Değişmez
Core sınırı" bölümü bunu zaten açıkça yazar:

> "Dış kod, skill, plugin, MCP veya agent ikinci bir Core, GoalState yazarı ya
> da izin otorisi olamaz."

Bu belge o kuralı, Hermes'e özgü somut sınırlarla genişletir. Aynı belgede
Hermes zaten "ilk karar `AL` değildir" olarak işaretlenmiştir ve "Hermes
browser provider" (#10) ile "Delegation/sub-agent" (#16) adayları
`ERTELENMİŞ` statüsündedir — yani bugün hiçbir üretim entegrasyonu yoktur ve
bu belge de onu başlatmaz.

## 2. Jarvis Core tek decision/completion authority olarak kalır

Core'un münhasır yetkisi şu dokuz kararla sınırlıdır ve dış agent/skill
bunlardan hiçbirini üstlenemez (`JARVIS_EXECUTION_ARCHITECTURE_V1.md` §3):

1. İsteğin sahibi kim?
2. Kullanıcı ne istiyor?
3. İş tek adımlı mı, çok adımlı mı, beklemeli mi?
4. Hangi domain ve capability kullanılacak?
5. Hangi izin sınıfı uygulanacak?
6. İş hangi durumda ve hangi adımdadır?
7. Sonuç yeniden denenebilir mi, uzlaştırma mı gerekir?
8. Kullanıcının hedefi gerçekten tamamlandı mı?
9. Hangi cevap veya artifact teslim edilecek?

Kod düzeyinde bu, `modules/core_state_reducer.py`'ın GoalState için **tek**
mantıksal yazıcı olmasıyla somutlaşır: `apply()` fonksiyonu her işlemi
`expected_version` ile fail-closed doğrular (`StaleStateError`), terminal
state'i (`done`/`cancelled`) değiştirilemez kılar (`TerminalStateError`) ve
her geçişi audit'e yazar. Bir dış agent/skill bu fonksiyonu çağırabilen başka
bir süreç veya bu fonksiyonun muadilini kendi tarafında yeniden uygulayan bir
mekanizma değildir; yalnız bu reducer'a girecek **girdi adayı** üretebilir.

## 3. Dış agent/skill yalnız öneri veya WorkerResult adayı üretir

`JARVIS_EXECUTION_ARCHITECTURE_V1.md` §5.1'deki ayrım bağlayıcıdır:

> "Model, Worker, Watcher, UI, Runtime Event ve Coding Backend yalnız
> Proposal/Result/Event üretir; Reducer `expected_version` denetimi,
> invariant, atomik compare-and-swap, `version + 1` ve audit uygular."

Hermes-benzeri bir adapter bu listedeki "Worker" rolüne eklenir, listenin
dışına çıkamaz. Ürettiği çıktı, `modules/worker_result.py`'daki
`worker_result.v1` şemasına uymayan hiçbir şey **değildir** — yani:

- Dış agent'ın çıktısı doğrudan "sonuç" veya "tamamlandı" sayılmaz; yalnız
  `worker_result.validate()` ve ardından `accept()` üzerinden geçen bir
  **WorkerResult adayı**dır.
- `accept()` çağrısı fence alanlarının (`owner`, `job_id`, `step_id`,
  `command_id`, `attempt`, `expected_job_version`, `capability_id`,
  `capability_version`, `input_digest`) Core'un kendi ürettiği `expected`
  değerleriyle bire bir eşleşmesini ister; eşleşmezse `FenceError` fırlatılır.
  Dış agent bu alanları kendi üretemez, yalnız Core'un verdiği command
  bağlamını geri yansıtabilir.
- `status` yalnız `succeeded`/`failed` olabilir; bu, dış agent'ın kendi
  içindeki ara durumların (plan, deneme, gözlem) Core Step'e çevrilmediği
  anlamına gelir (bkz. §15, Worker internal state).

## 4. GoalState yazamaz

`modules/goal_state_store.py::compare_and_swap` ve
`modules/core_state_reducer.py::apply` dışında hiçbir yol canonical
`goal_state.v1` dosyasını değiştiremez. Dış agent/skill:

- `goal_state.v1` JSON dosyasına doğrudan yazamaz.
- Reducer'ı taklit eden kendi "state" alanı üretip Core'a "zaten karar
  verildi" diye sunamaz; `worker_result_commit.py::commit()` her evidence'ı
  yalnız `core_state_reducer.apply(..., op='append_evidence', ...)` ile ekler
  ve `goal_state_store.compare_and_swap` çağırmadan önce diskteki mevcut
  sürümü (`current['version'] != accepted['expected_job_version']`) kontrol
  eder.
- `owner`, `job_id`, `goal`, `execution_mode` alanları reducer proposal'ıyla
  bile yamanamaz (`GOALSTATE_REDUCER_V1.md`); bir dış agent'ın bunları
  değiştirme yetkisi hiç yoktur.

## 5. Permission veremez veya yükseltemez

`modules/permission_gate.py::CLASSES` tek izin sınıf kümesidir ve Permission
Gate tek izin otoritesidir (`JARVIS_EXECUTION_ARCHITECTURE_V1.md` §10, değişmez
kural 8). Dış agent/skill:

- Kendi kendine `grant` üretemez; grant yalnız Core'un ürettiği şemaya göre
  (owner, capability_id, permission_class, target_id, scope, job_id, step_id,
  command_digest, max_uses, expires_at) var olur ve "Grant'i model, web, mail
  gövdesi veya belge içeriği değiştiremez" kuralı dış agent çıktısı için de
  geçerlidir.
- `deny` kararını `ask`'a veya `ask`'ı `execute`'a çeviremez; "Permission
  Policy `deny` kararı her yolda kesin rettir."
- `money_credential`, `system_config` ve dış hesap `external_write` gibi
  kilitli sınıflarda standing grant öneremez.

## 6. Effect başlatamaz

`modules/effect_journal.py` dosyasının docstring'i açıktır: "The journal
never executes, retries or reconciles effects." Effect intent/receipt
sözleşmesi (`_INTENT`, `_RECEIPT`) yalnız Core'un yan etkiden önce
kalıcılaştırdığı kayıttır. Dış agent/skill:

- Kendi başına dış dünyada bir yan etki (mail gönderme, dosya silme, dış
  hesap değiştirme, fiziksel komut) **başlatamaz**; yalnız Core'un zaten
  kurduğu Effect Policy → Worker çağrı zincirinin içinde, Core'un verdiği
  Command'e cevap üretebilir.
- `effect.state` değerini (`not_started/succeeded/failed/unknown`) kendi
  beyanıyla belirleyemez; bu durum Core'un reconciliation/receipt
  doğrulamasından geçer.
- "Bilinmeyen etki otomatik tekrar edilmez" kuralını, kendi retry mantığıyla
  aşamaz.

## 7. Global done/completed kararı veremez

Worker kendi capability'si için `success` dönebilir; bu global hedefin
tamamlandığı anlamına gelmez (`JARVIS_EXECUTION_ARCHITECTURE_V1.md` §14).
Dış agent/skill:

- Kendi çıktısında "tamamlandı", "done", "goal achieved" gibi bir alan
  taşısa bile bu, Completion Policy'nin yerine geçmez; `worker_result.v1`
  şemasında zaten böyle bir alan yoktur (`status` sadece
  `succeeded`/`failed`, global job state değildir).
- `modules/goal_state.py::STATES` kümesindeki (`pending/running/waiting/
  paused/failed/done/cancelled`) hiçbir değeri kendisi atayamaz; bu değerler
  yalnız `core_state_reducer.apply(op='set_state', ...)` üzerinden ve yalnız
  tanımlı `_TRANSITIONS` geçişleriyle değişir.
- `modules/outcome_contracts.py`'daki `OUTCOME-*` sözleşme kimlikleri dış
  agent tarafından taklit edilip Jarvis'e "zaten doğrulanmış sonuç" olarak
  sunulamaz; bu kimlikler Core/adapter tarafından atanır ve `validate_common`
  üzerinden denetlenir.

## 8. Adapter mevcut immutable fence/Reducer/CAS hattını bypass edemez

Üç ayrı immutable mekanizma vardır ve hiçbiri dış agent tarafından atlanamaz
veya taklit edilemez:

1. **WorkerResult fencing** (`modules/worker_result.py`): `_FENCE` alanları
   sabittir; `accept()` beklenen değerlerle tam eşleşme ister, aksi halde
   `FenceError`.
2. **Core State Reducer** (`modules/core_state_reducer.py`): her geçiş
   `expected_version` ile korunur; eski/stale proposal `StaleStateError`
   verir, terminal state değiştirilemez.
3. **CAS evidence hattı** (`modules/goal_state_store.py::compare_and_swap`):
   diskteki `version` beklenenle eşleşmezse `PersistedStateConflict`;
   `owner/job_id/goal/execution_mode` kimliği ve audit geçmişi CAS sırasında
   bile değiştirilemez.

Hermes-benzeri bir adapter bu üç mekanizmanın **önüne** bir "doğrudan
GoalState güncelleme" veya "fence'i atlayan kısayol sonucu kabul etme" yolu
ekleyemez. `modules/worker_result_commit.py::commit()`'in izlediği tek yol —
`worker_result.validate/accept` → `core_state_reducer.apply` →
`goal_state_store.compare_and_swap` — dış agent'ın ürettiği her aday için de
değişmeden kalır.

## 9. Capability Manifest ikinci tool engine değildir

`modules/capability_manifest.py`'ın docstring'i: "This is a compatibility
adapter, not a dispatcher or a second tool catalog. Existing execution,
discovery and permission boundaries remain their sources of truth; this
module only exposes their static metadata in a fail-closed shape."

Bu, Hermes-benzeri bir runtime'ın kendi skill/tool kataloğunu Jarvis'in
Capability Manifest'ine **eşit bir ikinci yürütme motoru** olarak
bağlayamayacağı anlamına gelir:

- Manifest satırları (`_FIELDS`: `id, version, source, permission_class,
  effect_policy, decision_authority, replay, reconciliation,
  evidence_contract`) yalnız **statik politika metadata'sı** taşır;
  `catalog()` fonksiyonu mevcut `task_tools`, `goal_tools` ve `tool_contract`
  kataloglarını okur, yeni bir dispatch mekanizması kurmaz.
- Bir Hermes adapter'ı Jarvis'e eklenecekse, kendi iç skill/tool listesini
  Jarvis'in çalıştıracağı paralel bir motor olarak sunamaz; yalnız tek bir
  `capability_id` arkasında, yukarıdaki WorkerResult/Permission/Effect
  zincirine tabi bir Worker olarak görünebilir (ileride, bu belge kapsamı
  dışında ayrı bir kabul sürecinde).

## 10. Callable/binding detayları manifest JSON'una girmez

`modules/capability_manifest.py::_FIELDS` içinde hiçbir çalıştırılabilir
referans (fonksiyon pointer'ı, IPC adresi, API key, binding) yoktur; mimari
belge bunu açıkça ayırır: "Statik metadata manifestte, çalıştırılabilir
Python/C# binding dispatcher katmanında tutulur"
(`JARVIS_EXECUTION_ARCHITECTURE_V1.md` §6). Bu ayrımın koddaki somut örneği
`modules/capability_hub.py`'dır: `public_binding()` bir endpoint/parametre
bağlamasını manifest JSON'una değil ayrı `service_store` kaydına yazar ve
`code_installed: False` ile yürütülebilir kod kurulmadığını teyit eder.

Hermes-benzeri bir adapter için sonuç: capability manifest kaydı (varsa)
yalnız `id/version/source/permission_class/effect_policy/decision_authority/
replay/reconciliation/evidence_contract` gibi politika alanları taşıyabilir;
Hermes'in kendi agent/gateway/plugin/skill çağırma mekanizmasının callable
veya bağlantı detayları (endpoint, token, process handle, plugin dosya yolu)
bu JSON'a **asla** girmez — ayrı, Core'un görmediği bir dispatcher/credential
katmanında kalır (`modules/capability_manifest.py`, `permission_gate`'in
"Secret yalnız yetkili sağlayıcı adaptöründe... en son noktada çözülür"
kuralıyla uyumlu, bkz. §27.2 `JARVIS_EXECUTION_ARCHITECTURE_V1.md`).

## 11. Production import, bağımlılık kurulumu veya runtime entegrasyonundan önce ayrı izole değerlendirme gerekir

`JARVIS_CAPABILITY_INTAKE_V1.md`'nin Hermes değerlendirmesi zaten bunu karar
olarak kaydetmiştir:

> "Bu nedenle ilk karar `AL` değildir: Hermes, sürümü sabitlenmiş kaynak
> incelemesi ve izole benchmark sonrası yalnız Worker/Adapter adayı olabilir.
> Doğrudan Jarvis Core'un yerine veya içine import edilmez."

Intake kapısı (aynı belge, "Intake kapısı" bölümü) her adayın `AL`/`UYARLA`
kararından önce şu kanıtları istediğini belirtir: sabit kaynak
sürümü/commit/lisans, Windows/Python/Node/dependency uyumu, çalıştırma sınırı
(read-only/local write/external write/physical), Worker/Adapter bağlanma
noktası, Permission/Effect/Evidence/Completion koşulları ve gerçek
acceptance/benchmark senaryosu. Bu belge o kapıyı **yeniden tanımlamaz**;
yalnız teyit eder ki bu adapter sınırı belgesi tek başına "üretim entegrasyonu
onayı" değildir — gerçek Hermes clone/import/dependency kurulumu veya runtime
bağlanması, bu belgenin kapsamı dışında, ayrı ve izole bir değerlendirme
turunda ele alınır.

## 12. Bu belgenin kapsamı

Bu belge yalnız **adapter authority sınırını** tanımlar: dış bir agent/skill
runtime'ı Jarvis'e bağlanacak olursa hangi kararları asla veremeyeceğini ve
hangi mevcut mekanizmaları asla bypass edemeyeceğini sabitler. Bu belge:

- Hermes'i veya başka bir dış runtime'ı içe aktarmaz, kurmaz veya
  çalıştırmaz.
- Yeni bir planner, ikinci bir execution engine veya yeni bir GoalState/
  Reducer/Permission/Effect mekanizması tanımlamaz.
- `tests/`, CI, watcher veya `AGENTS.md` davranışını değiştirmez.
- Worker kodu yazmaz; yalnız gelecekteki bir Worker/Adapter'ın uyması
  gereken sınırı, mevcut kod ve mimari kararlara dayanarak kayda geçirir.

Gelecekte bir Hermes-adapter pilotu başlatılırsa, o pilot bu belgedeki her
sınırı (§2–§10) ihlal etmediğini kanıtlamadan `AL` statüsüne geçemez; kanıt
`JARVIS_CAPABILITY_INTAKE_V1.md`'nin intake kapısı ve
`JARVIS_EXECUTION_ARCHITECTURE_V1.md` §30 "Yeni capability kabul standardı"
listesiyle aynı disiplinde sunulur.
