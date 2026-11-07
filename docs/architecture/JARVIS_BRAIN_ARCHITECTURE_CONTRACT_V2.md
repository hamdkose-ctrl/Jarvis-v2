# JARVIS BRAIN — Mimari Anayasa ve Uygulama Sözleşmesi V2

**Durum:** hedef mimari / uygulama tamamlanmış değildir.  
**Yol haritası otoritesi:** `docs/Jarvis_Yol_Haritasi.md`  
**Kod envanteri ve legacy sahiplik kaydı:** `docs/architecture/JARVIS_BRAIN_MIGRATION_MAP_V1.md`  
**Başlangıç main tabanı:** `bf15cd36e11270ab4dea223016500067972808ab` (2026-11-05)  
**Amaç:** ajan/oturum değişse dahi Brain'in ürün hedefinin, yetki sınırlarının ve uygulama sırasının değişmemesini sağlamak.

> Bu belge ikinci bir yol haritası, ikinci bir Brain veya yeni bir authority değildir. İstenen hedef davranışı ve değişmez kuralları tanımlar. Uygulama sırası ve durum yalnız ana yol haritasında tutulur. Migration map mevcut kodun hangi parçalarının korunacağını, taşınacağını veya emekli edileceğini gösterir.

---

## 1. Ürün tanımı

Jarvis, kelime/komut kalıplarına göre çalışan bir komut satırı botu değildir. Kullanıcının doğal dildeki amacını, konuşma bağlamını, daha önce başlatılmış işleri ve yeni mesajın bu işlerle ilişkisini anlamalı; birden fazla işi birbirine karıştırmadan yönetmeli; gerektiğinde beklemeli, kaldığı yerden sürdürmeli ve doğrulanmış sonucu teslim etmelidir.

Jarvis'in üç kimliği birbirinden ayrıdır:

1. **Karakter:** Jarvis'in sabit çalışma ve iletişim ilkeleri.
2. **Kullanıcı uyumu:** Kullanıcının açık tercihleri ve zaman içinde öğrenilen çalışma alışkanlıkları.
3. **Zekâ ve yürütme:** Doğal dili anlama, hedefleri ilişkilendirme, planlama, Core doğrulaması ve Worker yürütmesi.

Jarvis kullanıcıya uyum sağlar ama karakterini kaybetmez. Kullanıcıya yaranmak için yanlış bilgi vermez; gerektiğinde gerekçeli biçimde itiraz eder. Kişilik ve tercihler güvenlik/izin/etki kurallarını değiştiremez.

## 2. Değişmez mimari ilkeler

Bu ilkeler tüm PR'lar, ajanlar, model/provider değişiklikleri ve refactor'lar için bağlayıcıdır.

- **Tek Brain:** Genel kullanıcı niyeti ve konuşma-hedef ilişkisi için ikinci bir router/mini-brain kurulamaz.
- **Model birincil semantik karar sahibidir:** Kesin State/Fast protokolleri dışındaki serbest doğal dilde niyet, hedef ilişkisi ve capability seçimini model yapar. Deterministik regex/keyword sonucu modelin ön kararı veya veto şartı olamaz.
- **Core tek uygulama otoritesidir:** Brain önerir; Core capability, parametre, hedef, izin, risk, onay, effect, dispatch ve completion kurallarını doğrular/yürütür.
- **Candidate ≠ permission:** Aday veya referans bulmak, o hedef üzerinde işlem izni vermez.
- **Bir konuşma, çok sayıda bağımsız hedef:** Konuşma geçmişi ortak olabilir; her hedefin ayrı kimliği, yaşam döngüsü, ilerlemesi, plan sürümü ve sonucu bulunur.
- **Tek kanonik görev gerçeği:** GoalState mevcut canonical state authority olarak kalır. ExecutionRecord bir denemenin kaydıdır; ikinci GoalState veya bağımsız TaskState truth source oluşturulmaz. Alt görevler canonical GoalState aggregate/ilişki modelinin içinde temsil edilir.
- **Kısa iş hafif, uzun iş kalıcıdır:** Basit tek eylem ağır Planner/DAG döngüsüne sokulmaz. Çoklu kısa eylem kayıtsız string listesi olarak bırakılmaz. Uzun bağımlı iş kalıcı hedef ve görev grafiğidir.
- **Kör fallback yok:** Semantik model başarısızsa genel doğal dil regex'e düşürülerek çalıştırılmaz. İstek korunur, WAIT/clarify verilir.
- **İlerleme kanıta dayanır:** Worker'ın “bitti” sözü tek başına completion değildir.
- **Ajan devri tasarım kaybı yaratamaz:** Bir sonraki ajan yalnız yol haritası + bu sözleşme + migration map + exact SHA/handoff kaydına bakarak doğru sıradan devam edebilmelidir.

## 3. Hedef çalışma akışı

```text
USER INPUT (Text / Voice / Live / Phone / UI)
        |
        v
OWNER + REQUEST ID + SOURCE
        |
        v
EXACT STATE GATE
  yalnız bounded ve açık protokoller
        |
        v
DETERMINISTIC FAST / REFLEX GATE
  yalnız doğrulanmış, modelsiz kesin işlemler
        |
        v
ACTIVE CONTEXT + CANDIDATE EVIDENCE
  read-only, owner-bound, sınırlı ve provenance'lı
        |
        v
PRIMARY SEMANTIC BRAIN (model)
  intent + relation + target + task shape
        |
        v
STRICT PROPOSAL CONTRACT
        |
        v
CORE VALIDATION / APPROVAL / EFFECT POLICY
        |
        +---------------------------+
        |                           |
        v                           v
DIRECT ACTION / ACTION BATCH     GOAL MANAGER
        |                           |
        v                           v
SPECIALIST WORKERS              PLANNER / GOAL GRAPH
        |                           |
        +-------------+-------------+
                      |
                      v
             SCHEDULER / RESOURCE LEASE
                      |
                      v
                WORKER RUNTIME
                      |
                      v
              RESULT VERIFICATION
                      |
                      v
         PERSONA-AWARE RESPONSE / DELIVERY

Canonical persistence:
GoalState + ExecutionRecord + EffectJournal + WorkerResult/evidence
+ checkpoints/artifacts + resource lease/fencing metadata
```

Akıştaki her transport aynı Brain entry ve Core handoff sınırını kullanır. UI düğmesi gibi açıkça seçilmiş yapılandırılmış işlemler semantik serbest metin sayılmaz; yine Core doğrulamasından geçer.

## 4. Refleks katmanı: dar ve kesin sınır

Reflex katmanı model çağrısı olmadan çalışabilir. Ancak genel doğal dil yorumlayıcısı değildir.

Korunabilecek örnekler: açık bounded state protokolleri (`evet/hayır/iptal` yalnız tek ve sahibi belli pending işlem için), kesin `saat kaç`, açık sayısal `sesi 50 yap`, açık sayısal `parlaklığı 80 yap`, açık `hesap makinesini aç` gibi mevcut exact/fast sözleşmeleri.

Bir refleksin geçerli olması için koşulların tamamı aranır:

1. İfade/parametre sözleşmesi kapalı ve kesin olmalı.
2. Tek bir niyete ve tek bir hedefe karşılık gelmeli.
3. Serbest referans, zamansal yorum veya konuşma bağlamı çözümü gerektirmemeli.
4. Başka capability/domain'lerin önüne geçmemeli.
5. Geniş, substring veya “kelime içeriyor” eşleşmesiyle tetiklenmemeli.
6. Hedef ve argüman Core tarafından yine doğrulanmalı.

Yeni refleks eklemek, yeni doğal dil varyantları/fiil kökleri listesi eklemek değildir. Kullanıcı cümlesi bu kesin sözleşmeye uymuyorsa Semantic Brain'e gider. Exact State/Fast katmanının kapsamı genişletilecekse ayrı RED testleri ve false-positive kanıtı gerekir.

## 5. Model birincil anlamlandırma sözleşmesi

### 5.1 Modelin sorumluluğu

Her serbest doğal dil turunda model, yalnız mevcut deterministik sonucun boşluklarını doldurmaz. Tam kullanıcı mesajını, ilgili konuşma geçmişini, aktif hedef kimlik kartlarını ve owner-bound candidate/reference kanıtını değerlendirerek birincil anlam kararını üretir.

Model şunları anlamlandırır:

- Kullanıcı sohbet mi ediyor, tek bir işlem mi istiyor, birkaç işlem mi istiyor, uzun bir hedef mi tanımlıyor?
- Yeni görev mi başlatıyor, mevcut hedefe mi ekliyor, hedefi mi değiştiriyor, durduruyor mu, sürdürüyor mu, iptal mi ediyor?
- Mesaj hangi mevcut hedef(ler)e ait?
- Birden fazla hedef varsa hangi hedefler etkileniyor?
- İfade soru, olumsuzlama, düzeltme, ironi, dolaylı talep veya yalnız konu hakkında konuşma mı?
- Gerekli alan/parametre eksik mi; hangi açıklama sorusu gerekli?
- Eylemler bağımsız mı, sıralı mı, birbirine bağımlı mı?

Candidate Builder yalnız mevcut kaynaklardan aday/provenance çıkarır; bu bir semantik karar değildir. Model yalnız kendisine sunulan opaque candidate/reference slotlarını seçebilir. Dosya yolu, hesap, görev kimliği veya dış hedef uyduramaz. Kullanıcının kendi cümlesinin parçası olan semantik alanlar (mesaj alıcısı/gövdesi, kişi adı/numarası) modelden **alıntıyla** gelir: §5.4.

### 5.2 Önerilen düz JSON sözleşmesi

İlk uygulama düz ve küçük bir zarfla başlar. Karmaşık DAG ayrıntıları ilk anlama çağrısına yüklenmez.

```json
{
  "schema_version": "brain-understanding.v2",
  "operation": "action_batch",
  "conversation_relation": "NEW_REQUEST",
  "target_goal_ids": [],
  "goal": null,
  "actions": [
    {
      "action_id": "a1",
      "capability_id": "pc.media.action",
      "arguments": {"action": "stop"},
      "reference_slots": [],
      "depends_on": []
    },
    {
      "action_id": "a2",
      "capability_id": "pc.level.set",
      "arguments": {"property": "volume", "level": 30},
      "reference_slots": [],
      "depends_on": []
    },
    {
      "action_id": "a3",
      "capability_id": "calendar.read",
      "arguments": {},
      "reference_slots": [],
      "depends_on": []
    }
  ],
  "clarification": {
    "required": false,
    "question": null,
    "reason_code": null
  },
  "confidence": "HIGH"
}
```

Şema örnektir; capability adı ve argümanları gerçek Core manifest/allowlist ile sınırlanır. Alanların kesin tipi/enum'u kod sözleşmesinde tanımlanır. Model çıktısı permission, approved, execute, effect_allowed, completed, provider seçimi veya kullanıcı onayı alanı taşıyamaz.

`operation` kümesi:

- `chat`
- `direct_action`
- `action_batch`
- `create_goal`
- `continue_goal`
- `revise_goal`
- `add_task`
- `pause_goal`
- `resume_goal`
- `cancel_goal`
- `prioritize_goal`
- `clarify`

Kurallar:

- `direct_action`: tam bir eylem; Planner/DAG çağrılmaz.
- `action_batch`: iki veya daha fazla kısa eylem; her eylemin ayrı Core doğrulaması, sonucu ve hata durumu olur. `depends_on` boşsa bağımsızlık; doluysa açık bağımlılık ifade eder.
- Goal işlemleri: yalnız ilgili kısa Goal kimlik kartlarıyla anlamlandırılır. Ayrıntılı DAG ilk tur zarfına gömülmez.
- `target_goal_ids`: yalnız modele verilen mevcut kimliklerden seçilebilir. Kimlik verilmediyse yeni kimlik üretilemez.
- `reference_slots`: yalnız context'te sunulan, owner-bound ve provenance'lı adaylardan seçilebilir.
- `arguments`: capability şemasına bağlıdır. Basit semantic değerler (arama sorgusu, şehir, sayı, tarih ifadesi) önerilebilir; gerçek dosya yolu, token, credential, approval id veya başka owner verisi modelden kabul edilmez. Kullanıcı-sahibi alanlar (§5.4) ancak aynı isteğin cümlesinden alıntılanmış bir dayanakla kabul edilir.
- Düz/bozuk/eksik/fazla alanlı JSON reddedilir. Otomatik serbest metin onarımı veya ikinci regex yorumu yapılmaz.
- Güven düşükse, ilişki/target belirsizse veya birden fazla eşit hedef varsa `clarify`; model uydurmasıyla hedef seçilmez.

### 5.3 Kısa context kartları

Modele bütün DAG, tüm ExecutionRecord geçmişi veya tüm kullanıcı hafızası gönderilmez. Yalnız:
- Son ilgili konuşma turları (reset sınırı ve owner kontrolüyle),
- İlgili aktif hedeflerin kısa kartları: `goal_id`, özet, durum, plan sürümü, ilerleme özeti,
- Gerekli pending/approval kartları (işlem özeti ve opaque kimlik),
- Mevcut request'e ilgili owner-bound candidate/reference slotları,
- İzinli capability kataloğu ve ilgili parametre şemaları.

Ayrıntı gerekirse Goal Manager/Core kaynağından yüklenir. Modelin prompt'u gerçek verinin veya canonical state'in ikinci kopyası değildir.

### 5.4 Kullanıcı-sahibi alanlar ve dayanak (argument_sources)

Bazı alanların anlamı kullanıcının **kendi cümlesidir**: mesaj alıcısı ve gövdesi, kişi adı ve numarası. Bu alanlar için model hem yetenek kararına hem de alan değerlerine sahiptir; hiçbir yüzey (regex, kelime listesi, ikinci sınıflandırıcı) bu kararı modelin önünden veya ardından veremez. Karar ile yan etki arasındaki sınır değişmez:

- Zarf, kullanıcı-sahibi alan başına o alanı taşıyan **sözcükleri olduğu gibi** `argument_sources` içinde alıntılar. Alıntı yalnız bu isteğin cümlesinden gelir; önceki turdan veya modelin kendi üretimi bir metin dayanak sayılmaz.
- Core alıntıyı ve alanı aynı normalization ile (Türkçe İ/I katlaması, yalnız harf/rakam sinyali) doğrular: dayanak cümlede bulunmalı, alan değerini taşımalı ve alan değerinin kendisi de cümlede bulunmalıdır. Dayanaksız, taşan, çelişen ya da başka cümleden alıntılanan öneri **tamamen** reddedilir; kısmi kabul yoktur.
- Alan boş bırakılabilir ve boşsa dayanak gerekmez: eksik alıcı/gövde uydurulmaz, oturum kullanıcıya sorar. Yetki kararın sahibi olmayan bir yüzey tarafından "eksik" gerekçesiyle de verilmez.
- Biçim hükmü yine Core'dadır (numara normalleşmesi, ad sınırları, gövde tavanı, kapalı enum), **kimlik** hükmü defter sahibindedir (`messaging.find_contact` yalnız kayıtlı ve tekil eşleşmede kişi verir), onay mevcut `pending_msg` protokolündedir. Dayanak, "kullanıcı bunu söyledi" kanıtıdır; "böyle bir kişi var ve bu o" kanıtı değildir.
- Bir yeteneği bu nedenle modelden yasaklamak (deny-list) mimariyi tersine çevirir: yasağın yerini ham cümle grameri alır. Yasak kümesi yalnız **kullanıcı-sahibi alanı olmayan** ve tehlikesi başka biçimde kapatılamayan dar durumlar için vardır (bugün: `weather.city.set` / `weather.city.reset`).

### 5.5 Ölçüm ayrımı

Mock/fixture zarflı testler **bağlantı (wiring) ve yetki** kanıtıdır: zincirin doğru kapıdan geçtiğini, uydurma alanın reddedildiğini ve yan etki oluşmadığını ölçer. Modelin doğal dili gerçekten anlayıp anlamadığı ayrı, gerçek sağlayıcıyla ve önceden öğretilmemiş holdout cümleleriyle ölçülür (§16). İkisi birbirinin yerine geçmez.

## 6. Üç yürütme seviyesi

Her kullanıcı isteği Goal DAG'ine sokulmaz.

| Seviye | Ne zaman | Yol |
|---|---|---|
| `direct_action` | Tek, kısa işlem | Brain → Core → Worker |
| `action_batch` | Bir mesajda birkaç kısa işlem | Brain → Core (işlem başına) → Scheduler/Workers |
| Goal workflow | Uzun, bağımlı, devam etmesi gereken iş | Brain → Core → GoalState → Planner/DAG → Scheduler → Workers |

Örnek davranış:

- “Saat kaç?” → kesin/reflex yol.
- “Son notumu özetle.” → `direct_action`.
- “Müziği durdur, sesi 30 yap, takvimimi oku.” → `action_batch`.
- “Yapay zekâ gelişmelerini araştır, şirketleri karşılaştır, raporla ve dosyaya kaydet.” → kalıcı Goal workflow.

Planner çağrısı, anlamlandırma sonucu uzun hedef olduğu zaman başlar. Her basit işlem için ikinci bir LLM planlama çağrısı zorunlu kılınmaz.

## 7. Goal Resolver ve çoklu hedef

Konuşma tektir; hedefler birbirinden bağımsızdır.

- Her bağımsız hedef benzersiz `goal_id` taşır.
- Bir hedefin alt görevleri ve bağımlılıkları aynı canonical GoalState sahipliği altında tutulur.
- Yeni mesaj geldiğinde Brain aktif hedeflerin kısa özetlerini görür; mesajın yeni hedef, devam, ekleme, düzeltme, pause/resume/cancel/priority değişikliği olup olmadığını belirler.
- Modelin seçtiği hedef ID'si context'te sunulmuş olmalı; Core owner, status, version ve lifecycle'ı tekrar doğrular.
- “İlk işe dön”, “bunu da ona ekle”, “diğerini beklet” gibi ifadelerde eşit derecede olası birden fazla hedef varsa açıklama istenir.
- Bir hedefin pause/blocked/failed olması diğer bağımsız hedefleri otomatik iptal etmez.
- Bir hedefin kapatılması başka hedeflerin konuşma bağlamını silmez.
- Global `latest()` tek hedef seçicisi olarak kullanılmaz; sadece gözlem/compatibility için varsa açıkça böyle sınırlandırılır.

### GoalState ve yürütme kayıtları

- `GoalState`: hedefin kanonik lifecycle, kapsam, plan version, alt görev ilişkileri ve tamamlanma durumunun tek otoritesi.
- `ExecutionRecord`: her Worker/Planner denemesi, giriş/çıkış, attempt ve hata kaydı; GoalState'in yerine geçmez.
- `EffectJournal`: dış etki niyeti/receipt/sonuç kaydı; task state değildir.
- `WorkerResult`: typed sonuç ve evidence; tek başına hedefi completed yapmaz.
- Checkpoint/artifact kayıtları mevcut canonical state/evidence modeline bağlanır; ikinci kalıcı görev deposu oluşturmaz.

## 8. Planner ve görev grafiği

Planner yalnız uzun/bağımlı hedeflerde çalışır. Hedefi alt görevlere böler; her düğümde:
- task id ve parent goal id,
- beklenen sonuç ve input/output,
- bağımlı olduğu task ID'leri,
- gereken capability/worker,
- tamamlanma kriteri,
- risk/effect sınıfı için Core'a gönderilecek proposal,
- yeniden deneme ve bekleme politikası

tanımlanır.

DAG dinamiktir: yeni kullanıcı talimatı veya doğrulanmış bulgu planı değiştirebilir. Plan değişiminde `plan_version` yükselir. Eski plan sürümünden geç gelen Worker çıktısı otomatik olarak yeni plana yazılmaz; fencing/version kontrolünden geçer. Tamamlanmış, hâlâ geçerli kanıt tekrar yürütülmez.

Planner permission, provider, budget, data egress, risk veya effect authority sahibi değildir. Bu kararlar Core/Runtime policy'lerinde kalır.

## 9. Scheduler, ResourceLease ve Worker yaşam döngüsü

Bu alan mevcut Otonom/Serbest v1.1 tasarımıyla birleştirilir; ikinci Scheduler, ikinci Goal store veya farklı bir delegation sistemi oluşturulmaz.

Scheduler:
- Yalnız dependency'leri tamamlanmış ve Core tarafından yürütmeye uygun bulunan işleri seçer.
- Kaynak uygunluğunu ve kullanıcı önceliğini dikkate alır.
- Kaynak bağımsız işleri paralel çalıştırır; çakışan işleri sıraya alır.
- Her Worker için sahiplik, timeout, heartbeat, lease expiry ve fencing token yönetimini mevcut runtime sözleşmesiyle sağlar.
- Pause/cancel kontrolünü yeni Worker başlatmadan önce uygular.
- Duplicate wake/submit olaylarını coalesce/dedupe eder.

Kaynak anahtarı örnekleri: `pc_desktop`, belirli `browser_session`, belirli dosya/artifact kimliği, `gmail_account`, provider/quota scope. `filesystem` gibi kaba global kilit yerine mümkünse dosya/klasör kimliği bazında kilit tercih edilir. Aynı masaüstü oturumunu kullanan iki işlem aynı anda fare/klavye sahibi olamaz.

ResourceLease, kaynak kilidinin sahibi ve fencing bilgisidir; task progress veya GoalState gerçeği değildir. Lease süresi dolunca eski Worker'ın geç sonuçları fencing kontrolünden geçmeden kabul edilmez.

## 10. Approval, idempotency ve dış etki

Her onay:
- benzersiz `approval_id`,
- `owner`, `goal_id`, `task_id`,
- `plan_version`,
- etkilenecek target identity/digest,
- işlem özeti ve kapsamı,
- oluşturulma/sona erme zamanı,
- tek kullanımlık tüketim kaydı

ile belirli bir etkiye bağlanır.

“Evet” ancak tek bir geçerli ve bağlamca sahibi belli onay varsa o işlemi onaylar. Birden fazla bekleyen onay varsa netleştirme istenir. Onay başka hedefe, başka dosya sürümüne veya değiştirilmiş plana taşınamaz.

Dış etkiler için:
- operation-specific idempotency key kullanılır.
- Sağlayıcı receipt/sonuç belirsizse önce read-only reconciliation yapılır.
- “Exactly once” garantisi olmayan sistemlerde unknown outcome körlemesine tekrar edilmez.
- Dosya değişikliğinde identity/hash/undo veya telafi kaydı korunur.
- E-posta/mesaj gönderme gibi tekrarın zararlı olduğu işlemlerde duplicate prevention zorunludur.

## 11. Hata, kota, restart ve kısmi başarı

Model/provider hatası:
- Exact State/Fast ve kanıtlanmış modelsiz işlemler çalışmaya devam edebilir.
- Serbest doğal dilin semantiği modelden gelmelidir; model erişilemezse regex/keyword ile tahmini capability seçilip effect başlatılmaz.
- Kullanıcı isteği owner/request id ve güvenli şekilde gerekli provenance ile bekleyen semantic request olarak korunabilir.
- Model geri geldiğinde yeniden değerlendirilir; eski bağlam, hedef, izin ve approval tazeliği kontrol edilir.
- Ücretli sağlayıcıya sessiz geçiş yoktur. Mevcut ücretsiz/private route, privacy, quota, 12 saniye timeout ve cancellation sınırları korunur; politika değişikliği ayrı karardır.

Worker/process hatası:
- Heartbeat/lease expire olunca stale worker fencing ile etkisizleştirilir.
- Checkpoint'ten yalnız güvenle tekrar edilebilir alt adımlar başlatılır.
- Unknown external effect önce reconcile edilir.
- Bekleme, quota, approval, user input ve blocked durumları birbirinden ayrılır.

Batch:
- Her action kendi status/evidence kaydını üretir.
- Bir action başarısız olduğunda bağımsız kardeş action'lar mümkünse devam eder.
- Başarısız önkoşula bağlı adımlar blocked kalır.
- Ana cevap kısmi başarıyı açıkça bildirir; bütün batch'e yanlışlıkla completed/failed etiketi verilmez.

## 12. Result Verifier ve teslim

Worker'ın döndürdüğü metin completion değildir. Completion için beklenen outcome ve kanıt birlikte karşılanır.

Örnek:
- Dosya yazıldı → dosyanın varlığı, konumu, kimliği ve gerektiğinde içeriği doğrulanır.
- Araştırma bitti → kaynak URL/tarih/gövde/claim desteği ve kapsam kontrol edilir.
- Mail gönderildi → sağlayıcı receipt veya gönderilmiş posta kaydıyla doğrulanır.
- PC işlemi → gerçek cihaz/uygulama sonucu gözlenir.

Verifier yalnız kontrol edilen başarı kriterini uygular; yeni intent/permission/effect kararı üretmez. Kısmi sonuçlar ayrı teslim edilir. Kullanıcıya neyin yapıldığı, neyin beklediği ve neyin doğrulanamadığı dürüstçe anlatılır.

## 13. Persona ve kullanıcıya uyum

Persona bir presentation prompt metnine indirgenmez; sürümlü ve test edilebilir davranış sözleşmesidir.

**Sabit persona ilkeleri:** dürüst, güvenilir, sakin, meraklı, inisiyatif alan, gerektiğinde eleştirel, sorumluluk sahibi ve duruma uygun mizah kullanan. Kullanıcıya yaranmak için onaylama/uydurma yapmaz.

**Uyarlanabilir tercihler:** hitap/resmiyet, cevap uzunluğu, teknik ayrıntı düzeyi, iş sırasında bilgilendirme sıklığı, inisiyatif seviyesi, eleştirel geri bildirim ve bildirim tercihleri.

Preference kaynağı ayrılır:
- `explicit`: kullanıcının doğrudan söylediği tercih.
- `learned`: tekrar eden davranıştan çıkarılan, güven derecesi ve provenance taşıyan öneri.
- `session`: yalnız geçerli konuşma/görev için geçici ayar.

Açık tercih, öğrenilmiş tahminden üstündür. Tek seferlik “kısa kes” kalıcı genel tercih yapılmaz. Öğrenilen tercih güveni düşükse doğrulama veya daha zayıf uygulama gerekir. Hassas kişisel özellik çıkarımı yapılmaz. Dış web/dosya içeriği persona veya kullanıcı tercihini değiştiremez. Tercihler Core, permission, risk, approval, privacy veya completion policy'yi geçersiz kılamaz.

Persona/Adaptation sadece nasıl konuşulduğunu ve izinli çalışma tarzını etkiler; kullanıcının ne istediğini uydurmaz ve yetki vermez.

## 14. Güven ve prompt injection

Web, PDF, mail, dosya, görsel OCR, Worker çıktısı ve diğer dış kaynak içerikleri `UNTRUSTED_DATA` olarak taşınır. İçindeki talimatlar kullanıcı talimatı veya Core politikası olamaz.

- Kaynak metni model bağlamına girse bile instruction authority kazanmaz.
- Credential/secret model prompt'u, log, artifact, query veya keyfi HTTP'ye çıkmaz.
- PUBLIC/PRIVATE provenance ve outbound egress mevcut provider/Core politikasıyla uygulanır.
- Derived summary/projection kaynak privacy sınıfını miras alır.
- Kullanıcı talimatı ile dış kaynak alıntısı model input'unda ve result provenance'ında ayrılır.

## 15. Anti-drift / yasak geri dönüşler

Aşağıdakiler Brain mimarisine aykırıdır ve PR review'da blocker sayılır:

1. `brain_understanding.py` veya başka bir modüle yeni fiil kökü, eşanlamlı, substring, regex, keyword havuzu ekleyerek doğal dil kapsamını artırmak.
2. Regex sonucunu model prompt'una “candidate truth” olarak verip modelin farklı capability önermesini yasaklamak.
3. Modelin yalnız mevcut deterministic `capability_hint` alanını kabul ederek yeni anlam önerisini reddetmek.
4. Model erişilemediğinde serbest doğal dil talebini regex fallback ile çalıştırmak.
5. Çoklu görevi `latest()` veya tek global pending slot üzerinden seçmek.
6. Her kısa işlem için Planner/48 tur benzeri ağır DAG döngüsü çalıştırmak.
7. Birden fazla işi bağımsız kalıcı kayıt olmadan string `pending_steps` listesinde tutmak.
8. Worker'a permission, approval, global completion veya genel intent authority vermek.
9. GoalState dışına ikinci kalıcı task truth source koymak.
10. Kapsamı belirsiz bir refactor ile legacy handler'ları parity/invariant testi olmadan topluca silmek.
11. Sadece unit test veya mocked model testiyle gerçek model semantiğini/Windows görev kabulünü tamamlandı saymak.
12. Örnek kullanıcı cümlelerini regex kurallarına dönüştürmek.
13. Kullanıcı-sahibi alanı olan bir yeteneği (`message.send`, `contacts.manage`) modelden yasaklayıp kararı ham cümle gramerine bırakmak; ya da tam tersi, yasağı kaldırıp grameri "geçici" olarak başka dosyaya/ada taşımak.
14. §5.4 dayanağını ikinci bir semantik sınıflandırıcıyla değiştirmek: Core'da kelime listesi/eş anlamlı havuzuyla "kullanıcı bunu söyledi mi" hükmü vermek.

**Regex nerede kalabilir?** Exact State/Fast protokolleri, kapalı enum/schema parsing, URL/path/JSON doğrulaması, güvenlik invariant'ı, domain'in capability seçildikten sonra kullandığı bounded syntax grammar ve metin normalizasyonu. Bu kullanımlar genel kullanıcı niyeti seçemez.

**Guard:** bu iki madde sözel değildir. `modules/architecture_guard.py` ARCH-008 ile capability **adinin** değil **sahibinin** modül-düzeyi sabit atamasını denetler: `message.send` / `contacts.manage` literalleri ve kanonik sabitleri yalnız sahibi modülde (`brain_understanding`) ve Core'un kapalı sözleşme tablolarında (`CORE_INTENTS`, `_USER_OWNED_ARGUMENT_SLOTS`, guard'ın kendi kümesi) görünebilir. Dosyaya taşıma, yeniden adlandırma veya sabiti import etme denetimi kapatmaz; numara regex'i, kapalı enum ve tip sınırları gibi biçim/güvenlik denetimleri yetenek adı taşımadığı için kapsam dışıdır.

## 16. Kabul ve ölçüm standardı

### Semantic acceptance
- Daha önce öğretilmemiş doğal Türkçe varyantlar: dolaylı anlatım, eşanlamlı, deyim, yazım/ses tanıma farklılığı, eksiltili ifade.
- Soru ≠ komut; olumsuzlama ≠ onay; alıntı/dış talimat ≠ kullanıcı talimatı.
- Yeni iş / devam / ekleme / düzeltme / pause / resume / cancel / priority / hedef referansı.
- Birden fazla aktif Goal arasından doğru hedef seçimi veya gerektiğinde clarify.
- Model unavailable/429/malformed JSON/timeout/cancel senaryoları.
- Modelin hayali capability, path, recipient, goal id, approval, permission, provider üretememesi.

Mevcut `tests/data/yonlendirme_cumleleri.json`, 465 Brain baseline, #516 ve #520 korpusları **evaluation/regression verisidir; regex kural kitabı değildir.** Korpus büyütülebilir, fakat model prompt'unda deterministik eşleştirme tablosu olarak kullanılmaz; train/evaluation ayrımı ve daha önce görülmemiş holdout cümleleri korunur. Kullanıcı-sahibi alanların (§5.4) holdout'u `tests/data/brain_semantic_holdout_dilim2.json` dosyasındadır ve `scripts/brain_semantic_holdout.py` ile **yalnız üretimle aynı ücretsiz bulut rotası üzerinden** ölçülür: rota uygun değilse script ölçümü yapmaz ve elenme gerekçeleriyle `ÖLÇÜLEMEDİ` döner; kapıyı gevşetmek, yerel/ücretli rotaya ya da deterministik kapıya düşmek bu ölçümün kanıt değeri yoktur.

Plan hedefi: semantik niyet + hedef seçiminde en az %95 doğruluk; kritik yanlış effect **0**. Bu eşik sadece aggregate skorla geçilemez: kritik test sınıfları ayrı ayrı raporlanır ve her sınıf için false-positive/false-negative incelenir.

### Product / Windows acceptance
En az 15–20 gerçekçi uçtan uca senaryo: uzun araştırma, dosyadan rapor, araya mail görevi, göreve geri dönüş, aynı anda bağımsız işler, aynı dosyaya çakışma, PC kaynağı kilidi, bir adımda onay, bir adımda hata, kota bekleme, restart, unknown effect, kısmi batch, gerçek artifact teslimi ve persona tercihleri.

Mock test model wiring'i kanıtlar; gerçek ücretsiz sağlayıcı kabulü ayrı raporlanır. Exact-head Windows CI ve aynı SHA gerçek PC watcher PASS olmadan PR kabul edilmiş/Brain CLOSED sayılmaz.

## 17. Ajanlar arası devir ve yol haritasına bağlılık

Her PR/ajan devri şu bilgileri yazılı bırakır:

- Work package ID ve bu paketin tek cümlelik amacı.
- Başlangıç `main` SHA'sı; branch adı; güncel head SHA.
- Kapsam içi ve açıkça kapsam dışı dosyalar.
- Değiştirilen modüller ve her modülün yeni sorumluluğu.
- Önce başarısız olan RED test ve beklenen davranış.
- Çalıştırılan targeted test, `python -X utf8 -m modules.validation` sonucu, Windows CI run + exact head SHA.
- Aynı head için PC watcher sonucu + exact SHA.
- Açık blocker, bilinçli ertelenen konu ve bir sonraki izinli work package.
- Yol haritasındaki durum güncellemesi; merge edilmemiş iş “tamamlandı” işaretlenmez.

Ajan, yalnız kendi PR kapsamındaki işi yapar. Yeni mimari fikri çıkarsa mevcut pakete gizlice eklemez; önce bu sözleşmeye göre sınıflandırır ve roadmap backlog'una kaydeder. Başka açık Brain PR'ı varsa aynı dosya/authority alanında paralel PR açılmaz; branch/diff sahipliği doğrulanır.

Devir sırasında bu belgenin “Değişmez mimari ilkeler” ve “Anti-drift” bölümleri okunmadan kod değişikliği başlatılmaz. Bir sonraki ajan bu belgede tanımlı hedefi değiştiremez; değişiklik ancak kullanıcı kararı ve yeni ADR/roadmap güncellemesiyle yapılır.

---

## 18. Bu belgenin kapanış anlamı

Bu belge yazıldığı için hiçbir kod maddesi tamamlanmış sayılmaz. Hedef mimariyi sabitler. Gerçek kapanış; ana yol haritasındaki her BRAIN paketi için kod bağlantısı, test, migration/caller-zero, exact-head Windows CI ve aynı-SHA PC kabul kanıtlarının birlikte gelmesiyle yapılır.

**Nihai ürün testi:** Jarvis bir uzun işi yürütürken kullanıcı araya başka bağımsız iş verebilmeli; Jarvis ikinci işi hemen anlamalı, ilk işi kaybetmemeli, kaynak çakışmasını önlemeli, her iki işi ayrı takip etmeli ve kullanıcı ilk işe döndüğünde kaldığı yerden devam etmelidir. Bunu kalıp dışı doğal Türkçeyle yapmalı; tutarlı karakterini ve kullanıcı tercihlerini korumalıdır.
