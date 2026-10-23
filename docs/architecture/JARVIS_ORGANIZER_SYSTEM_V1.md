# Organizer System v1 — Nihai Kilitli Mimari Kararı

**Durum:** Ana mimariye bağlı ve kabul edildi — 23 Ekim 2026

## 1. Domain kararı

Organizer System, Jarvis’in yedinci ana domain’i olacaktır:

```text
pc
web
document
study
organizer
communication
developer
```

Organizer ayrı bir execution engine değildir.

Mevcut:

```text
Jarvis Core
Job / Step
Capability Manifest
Permission Gate
Command / Result / Event
Evidence / Effect
Completion Policy
```

omurgasını kullanır.

Organizer’ın görevi:

> Kullanıcının görev, not, etkinlik, hatırlatma, günlük, plan, proje, milestone ve rutin kayıtlarının organizasyon anlamını yönetmektir.

---

# 2. Organizer temel varlıkları

```text
ORGANIZER SYSTEM
├─ Task
├─ Note
├─ Event
├─ Reminder
├─ CalendarLink
├─ JournalEntry
├─ Plan
│  ├─ DayPlan
│  └─ WeekPlan
├─ Project
├─ Milestone
└─ Routine
```

Bu nesneler ortak kuralları paylaşır ancak **tek dev veri kaydı oluşturmazlar**.

Her varlığın kendi şeması ve uygun deposu bulunabilir.

---

# 3. Ortak Organizer envelope

Organizer varlıklarında ortak kimlik ve sahiplik alanları kullanılmalıdır:

```yaml
entity:
  entity_type: task
  entity_id: task-17

  owner: hamdi

  schema_version: 1
  entity_version: 4

  created_at: ""
  updated_at: ""

  origin:
    type: user

  derived_from: []
```

Ortak alanlar:

```text
entity_type
entity_id
owner
schema_version
entity_version
created_at
updated_at
origin
derived_from
```

## Ana kural

> Ortak model, tek fiziksel kayıt anlamına gelmez.

Task, Journal, Project ve Event kendi domain şemalarına sahip olur.

## Uygulama kuralı: ortak validation tabanı

`schema_version`, `entity_version`, `owner`, zaman damgaları, `origin` ve `derived_from` her varlıkta elle yeniden tarif edilmez. Tek bir `OrganizerEntityEnvelope` validation şeması veya eşdeğer ortak bileşim kullanılır. Task, Note, Event, Reminder, JournalEntry, Plan, Project, Milestone, Routine ve CalendarLink bu tabanı genişletir. Dil seviyesinde kalıtım şart değildir; tek doğrulama tanımı ve aynı invariant davranışı şarttır.

---

# 4. Tek provenance alanı: `derived_from`

Organizer içinde:

```text
source_refs
evidence_refs
```

gibi ikinci ve üçüncü provenance isimleri oluşturulmaz.

Tek ilişki:

```yaml
derived_from:
  - ev-17
  - ev-23
```

olarak kullanılır.

Doğrudan kullanıcı kaydı:

```yaml
origin:
  type: user

derived_from: []
```

olabilir.

Kaynak veya analizden türetilen Organizer verisinde `derived_from` zorunludur.

---

# 5. Task

Task kullanıcının yapılacak işidir.

Core Job ile aynı şey değildir.

```yaml
task:
  entity_id: task-17
  owner: hamdi

  title: Raporu hazırla
  description: ""

  status: pending
  priority: normal

  project_id: project-4
  parent_task_id: null

  depends_on: []

  scheduled_for: null
  due_at: ""

  estimated_minutes: 60

  recurrence: null

  origin:
    type: user

  derived_from: []

  created_at: ""
  updated_at: ""
  completed_at: null
```

Durumlar:

```text
pending
in_progress
waiting
completed
cancelled
```

## Kritik ayrım

```text
Organizer Task
= Kullanıcının yapılacak işi

Core Job
= Jarvis'in bir kullanıcı hedefini yürütmesi
```

Bir Task, bir veya daha fazla Jarvis Job başlatabilir; ama aynı nesne değildir.

## Task bağımlılık doğrulaması

Task ilişkileri model önerisi değil, domain invariant’ıdır.

1. `parent_task_id` ve `depends_on` ile referans verilen Task aynı `owner`a ait olmalıdır.
2. Task kendisine bağımlı olamaz.
3. Dependency graph döngü içeremez; döngü kaydetme aşamasında reddedilir.
4. Tamamlanmamış zorunlu dependency varken Task otomatik tamamlanmış sayılamaz.
5. Dependency silinirse ilişki sessizce yok edilemez; relation cleanup yapılır veya `CONFLICT` üretilir.
6. Başka Project’e dependency kuruluyorsa açık domain doğrulaması gerekir.
7. Model dependency önerebilir; invariant kontrolünü kod yapar.

---

# 6. Note

```yaml
note:
  entity_id: note-23
  owner: hamdi

  title: Toplantı notları
  body: ""

  tags:
    - proje-x

  project_id: project-4
  linked_task_ids: []
  linked_person_ids: []

  origin:
    type: user

  derived_from: []

  created_at: ""
  updated_at: ""
```

Not:

- göreve bağlanabilir,
- projeye bağlanabilir,
- Event’e bağlanabilir,
- aday Task üretebilir,
- kullanıcı isterse JournalEntry’ye dönüştürülebilir.

Ancak bunlar otomatik yan etki anlamına gelmez.

---

# 7. Yerel Event

Organizer’da ayrı bir yerel Event nesnesi bulunmalıdır.

```yaml
event:
  entity_id: event-17
  owner: hamdi

  title: Proje toplantısı

  all_day: false

  starts_at: 2026-10-24T10:00
  ends_at: 2026-10-24T11:00
  timezone: Europe/Istanbul

  location: ""

  project_id: project-4

  origin:
    type: user

  derived_from: []

  created_at: ""
  updated_at: ""
```

Event:

> Kullanıcının planındaki zamanlanmış olaydır.

External Calendar Event ile aynı kayıt değildir.

## Event zaman doğrulaması

- Zamanlı Event için `starts_at < ends_at` zorunludur.
- `timezone` geçerli bir IANA timezone olmalıdır.
- `all_day: true` ayrı temsil edilir; saat alanları normal zamanlı Event gibi yorumlanmaz.
- DST dönüşümleri timezone-aware yapılır.
- Timezone’suz dış kayıt doğrudan yerel Event’e çevrilmez; belirsiz yerel saat doğrulanmadan kaydedilmez.
- External provider zamanı ile Organizer zamanı dönüşümü receipt/provenance ile izlenebilir kalır.

---

# 8. Reminder

Reminder ile Event farklı nesnelerdir.

```text
Event
= Belirli zamanda gerçekleşen veya planlanan olay

Reminder
= Belirli zamanda/koşulda kullanıcıya bildirim üretme isteği
```

Önerilen model:

```yaml
reminder:
  entity_id: reminder-12
  owner: hamdi

  message: Raporu gönder

  trigger:
    type: datetime
    at: 2026-10-24T09:00
    timezone: Europe/Istanbul
    recurrence: null

  linked_task_id: task-17
  linked_event_id: null

  delivery_channels:
    - jarvis

  state: scheduled

  last_delivery_state: null
  next_trigger_at: ""

  origin:
    type: user

  derived_from: []
```

Durumlar:

```text
scheduled
triggered
delivered
missed
snoozed
cancelled
```

## Kritik ayrım

```text
triggered
≠
delivered
```

Zaman geldiğinde reminder tetiklenebilir ama kullanıcıya ulaşmamış olabilir.

## Teslim idempotency

Her occurrence için deterministik bir `trigger_id` üretilir:

```yaml
delivery_attempt:
  trigger_id: "reminder-12:2026-10-24T09:00+03:00"
  reminder_id: reminder-12
  channel: jarvis
  state: delivered
  attempted_at: ""
  delivered_at: ""
```

Aynı occurrence uygulama yeniden başladığında ikinci bir bildirim üretmez. `late_delivery` yeni occurrence değildir ve aynı `trigger_id` ile yürür. Tetikleme ile teslim ayrı kayıtlardır.

---

# 9. Jarvis kapalıyken Reminder davranışı

Reminder politikası açıkça tanımlanmalıdır.

Yerel reminder için en az şu durum düşünülmelidir:

```text
Jarvis açıktı
→ zamanında trigger
→ delivery denendi

Jarvis kapalıydı
→ trigger zamanı kaçtı
→ missed
```

Jarvis yeniden açıldığında politika capability’ye göre:

```text
late_delivery
skip
ask_user
```

olabilir.

Örnek:

```yaml
missed_policy:
  action: late_delivery
  max_delay_minutes: 120
```

Bulut tabanlı bağımsız reminder ileride eklenirse ayrı provider capability’si olur.

---

# 10. JournalEntry

Journal sıradan Note değildir.

```yaml
journal_entry:
  entity_id: journal-51
  owner: hamdi

  occurred_on: 2026-10-23
  timezone: Europe/Istanbul

  title: Bugünün değerlendirmesi
  body: ""

  tags: []

  linked_task_ids: []
  linked_project_ids: []
  linked_event_ids: []

  origin:
    type: user

  derived_from: []

  sensitivity: private

  created_at: ""
```

## Journal gizlilik kuralları

1. Journal yalnız açık kullanıcı niyetiyle kalıcılaştırılır.
2. Sohbet geçmişi otomatik JournalEntry olmaz.
3. Mail otomatik JournalEntry olmaz.
4. Hoca oturumu otomatik JournalEntry olmaz.
5. Teknik Job/Audit kayıtları Journal değildir.
6. “Bugün yaptıklarımı günlüğe yaz” denirse doğrulanmış Organizer kayıtlarından taslak hazırlanabilir.
7. Taslak, kullanıcı kaydetme niyeti olmadan JournalEntry olmaz.
8. Bir kişinin Journal verisi başka kişinin bağlamında aranamaz.
9. Kullanıcı açıkça istemedikçe Journal içeriği modele gönderilmez.
10. Journal ile teknik audit farklı depolarda tutulur.

## Kritik ayrım

```text
Journal
≠ Sohbet geçmişi
≠ Teknik log
≠ Daily Briefing
```

---

# 11. Plan

Plan anlık rapor olmaktan çıkarılıp kalıcı bir Organizer nesnesi olabilir.

```yaml
plan:
  entity_id: plan-2026-10-23
  owner: hamdi

  plan_type: day

  period_start: 2026-10-23
  period_end: 2026-10-23

  goals: []

  blocks:
    - start: 09:00
      end: 10:00
      timezone: Europe/Istanbul
      task_id: task-17

  origin:
    type: organizer_policy

  derived_from:
    - task-17
    - event-12

  created_at: ""
  updated_at: ""
```

## Plan ile Actual ayrımı

```text
PLAN
= Ne yapmayı planladık?

ACTUAL
= Gerçekte ne oldu?
```

Bu sayede:

```text
planlanan süre
gerçekleşen süre

planlanan görev
tamamlanan görev

planlanan sıra
gerçek yapılan sıra
```

karşılaştırılabilir.

---

# 12. Plan önceliği deterministik olmalı

Planlama önceliği yalnız modele bırakılmaz.

Kod tabanlı sinyaller:

```text
yaklaşan deadline
+ gecikmiş görev
+ task priority
+ bağımlılıklar
+ tahmini süre
+ takvimdeki boşluk
+ mevcut Event çakışmaları
+ Study tekrar ihtiyacı
+ yarım kalan iş
```

üzerinden değerlendirilir.

Model:

- açıklama yapabilir,
- alternatif plan önerebilir,
- doğal dilde sunabilir.

Model tek başına:

- deadline değiştiremez,
- priority değiştiremez,
- kalıcı zaman bloğu oluşturamaz.

Kalıcı değişiklik normal Core/Permission/Capability yolundan geçer.

---

# 13. Project

Mail thread veya proje adı geçen belge doğrudan Project değildir.

Project bağımsız Organizer varlığıdır.

```yaml
project:
  entity_id: project-4
  owner: hamdi

  title: Jarvis C# PC geçişi

  status: active

  goals: []

  milestone_ids: []
  task_ids: []
  note_ids: []
  event_ids: []

  target_date: null

  origin:
    type: user

  derived_from: []

  created_at: ""
  updated_at: ""
```

---

# 14. Milestone

```yaml
milestone:
  entity_id: milestone-2
  owner: hamdi

  project_id: project-4

  title: İlk gerçek C# kabul testi

  due_at: null
  status: pending

  origin:
    type: user

  derived_from: []
```

Project ile Task aynı şey değildir.

Milestone:

> Projenin önemli ilerleme noktasıdır.

Task:

> Yapılması gereken somut iştir.

---

# 15. Mail tabanlı iş bilgisi Candidate olmalı

Mail başlığı, sender veya tarih kesin Organizer gerçeği değildir.

Akış:

```text
OUTLOOK / MAIL
↓
Communication / WorkTrack analizi
↓
Candidate
↓
confidence + provenance
↓
Core / policy / gerekirse kullanıcı
↓
Organizer Project / Task / Event
```

Örnek:

```yaml
candidate:
  candidate_id: candidate-41
  owner: hamdi

  proposed_entity_type: task

  proposed_data:
    title: Teklif raporunu gönder
    due_at: 2026-10-28

  confidence: medium

  derived_from:
    - mail-evidence-88
```

Mail thread:

> Project değildir.

Yalnız Project’e bağlanabilecek evidence veya signal olabilir.

---

# 16. Routine

Routine tekrarlayan kullanıcı niyetidir.

```yaml
routine:
  entity_id: routine-8
  owner: hamdi

  title: Haftalık plan

  schedule:
    type: weekly
    weekday: monday
    timezone: Europe/Istanbul

  action_template:
    capability_id: organizer.plan.prepare
    capability_version: 1

  enabled: true

  origin:
    type: user

  derived_from: []
```

Akış:

```text
Routine
↓
Runtime Watcher
↓
Immutable Event
↓
Core
↓
Capability
↓
Permission Gate
```

---

# 17. Routine gelecekteki işlemlere genel izin değildir

Routine oluşturmak:

> Gelecekteki tetikleme niyetini kaydetmek

anlamına gelir.

Şunlar için genel sınırsız izin değildir:

```text
mail gönderme
mesaj gönderme
yayınlama
satın alma
sistem değiştirme
destructive işlem
```

Her tetiklenmede:

1. Routine owner doğrulanır.
2. Capability hâlâ kayıtlı mı kontrol edilir.
3. Capability version/policy doğrulanır.
4. Action template değişmemiş mi doğrulanır.
5. Permission Gate çalışır.
6. Gerekirse kullanıcı onayı alınır.

Routine template model veya dış içerik tarafından değiştirilemez.

Template değişirse önceki kullanıcı onayı yeni template için geçerli sayılmaz.

---

# 18. CalendarLink

CalendarLink yerel Organizer Event ile dış takvim kaydı arasındaki senkronizasyon ilişkisidir.

```yaml
calendar_link:
  entity_id: calendar-link-7
  owner: hamdi

  organizer_event_id: event-17

  provider: google
  external_calendar_id: primary
  external_event_id: evt-991

  external_version: etag-7

  sync_direction:
    organizer_to_provider

  sync_state:
    synced

  last_synced_at: ""

  last_error: null
```

Olası sync state:

```text
pending
synced
conflict
error
detached
```

Dış sağlayıcı değiştiyse eski Organizer verisi sessizce üzerine yazılmaz.

```text
external_version değişti
↓
CONFLICT / reconciliation
```

üretilebilir.

---

# 19. Calendar System of Record sınırı

Yerel Organizer Event:

```text
System of Record
= Organizer
```

Google/Outlook Event:

```text
System of Record
= dış takvim sağlayıcısı
```

CalendarLink:

```text
System of Record
= Jarvis Organizer/Communication bağlantı deposu
```

Communication:

> dış sağlayıcıyla işlem yapan adaptördür.

Organizer:

> kullanıcının planlama anlamını yöneten domain’dir.

---

# 20. WorkTrack kişi ayrımı

Mevcut global:

```text
work_projects
work_vip
```

gibi kayıtlar Organizer geçişinde kullanıcıya özel hale getirilmelidir.

Yeni kayıt:

```text
owner = hamdi
```

veya:

```text
owner = hasan
```

taşır.

## Migration kuralı

Eski global veriler:

> bütün kullanıcılara otomatik kopyalanmaz.

Önce gerçek sahip belirlenir.

Belirsizse:

```text
migration_requires_owner
```

olarak bekletilir.

Bu özellikle kişi izolasyonunu korumak için önemlidir.

---

# 21. Capability izin başlangıç eşlemesi

Ana Permission Gate sınıfları:

```text
read
local_reversible
local_destructive
external_write
message_out
publish
money_credential
system_config
physical
```

`external_write`, kullanıcının özel dış hesabındaki bir kaydı oluşturma, değiştirme veya silme işlemidir. Başlangıç politikası `ask`tır; açık `owner`, kesin provider/account/resource hedefi, idempotency ve reconciliation zorunludur. Başlangıçta standing grant verilmez. Silme riski yeni bir permission sınıfıyla değil Effect Policy ile ifade edilir.

```yaml
effect_policy:
  type: external_write
  destructive: true
  compensation_capability: null
```

| Capability | Permission |
|---|---|
| `organizer.task.list` | `read` |
| `organizer.task.create/update/complete` | `local_reversible` |
| `organizer.task.delete` | `local_destructive` |
| `organizer.note.create/update` | `local_reversible` |
| `organizer.note.delete` | `local_destructive` |
| `organizer.event.create/update` | `local_reversible` |
| `organizer.event.delete` | `local_destructive` |
| `organizer.journal.create` | `local_reversible` + açık kullanıcı niyeti |
| `organizer.reminder.create` | `local_reversible` |
| `organizer.routine.create` | `local_reversible` |
| `organizer.project.create` | `local_reversible` |
| Google/Outlook takvim okuma | `read` |
| Dış takvim etkinliği oluşturma/güncelleme | `external_write` |
| Dış takvim etkinliği silme | `external_write` + destructive Effect Policy |
| Mail gönderme | `message_out` |
| Sosyal paylaşım | `publish` |
| Fiziksel cihaz etkisi | `physical` |

Bu tablo Capability Manifest’in başlangıç policy mapping’idir.

---

# 22. Existing data migration

Organizer boş bir sistem olarak başlatılmamalıdır.

Mevcut:

```text
profile.tasks
profile.items / notes
profile.events
work_projects
work_vip
```

gibi veriler korunmalıdır.

Geçiş:

```text
LEGACY DATA
↓
READ-ONLY LEGACY ADAPTER
↓
OWNER + IDENTITY VALIDATION
↓
TRANSFORM
↓
NEW ORGANIZER SCHEMA
↓
COUNT / CONTENT VALIDATION
↓
REFERENCE REMAPPING
↓
NEW PATH ACCEPTANCE
↓
ATOMIC WRITE AUTHORITY CUTOVER
↓
OLD WRITE PATH DISABLED
```

Migration boyunca aynı mantıksal kayda eski ve yeni depoda birlikte yazılmaz. Cutover öncesinde legacy depo tek write authority’dir; yeni şema shadow/read-only doğrulanır. Kabul tamamlanınca write authority tek kontrollü geçişle yeni depoya alınır ve eski yol salt okunur uyumluluk adaptörü olur. Geçiş sırasında değişen kayıtlar çift yazmayla değil kısa write pause, delta migration veya version kontrollü yeniden oynatma ile taşınır.

---

# 23. Legacy ID eşleme

Eski numeric ID'ler kaybolmamalıdır.

Örnek:

```yaml
legacy_mapping:
  source_type: task
  legacy_id: 12
  organizer_id: task-17
```

Böylece:

- UI linkleri,
- reminder bağlantıları,
- mevcut komut referansları

bozulmaz.

Migration bittikten sonra bile gerekli süre boyunca legacy lookup desteklenebilir.

---

# 24. Migration doğrulaması

Migration completion için en az:

```text
eski kayıt sayısı
yeni kayıt sayısı

başlık / metin
tarih
owner
done/status
reminder ilişkileri
event ilişkileri
```

karşılaştırılmalıdır.

Kayıp veya belirsizlik varsa eski write yolu kapatılmaz.

---

# 25. Organizer Candidate ortaklaştırması

Document, Study, Communication ve Organizer için farklı Candidate motorları kurulmaz.

Ortak candidate envelope kullanılabilir:

```yaml
candidate:
  candidate_id: candidate-55
  owner: hamdi

  target_domain: organizer
  proposed_entity_type: event

  proposed_data:
    title: Matematik sınavı
    starts_at: 2026-11-03T09:00
    timezone: Europe/Istanbul

  confidence: high

  derived_from:
    - ev-88

  state: pending
```

Durumlar:

```text
pending
accepted
corrected
rejected
superseded
```

Domain-specific validation yine Organizer tarafından yapılır.

## Candidate confidence ile Evidence trust ayrımı

```text
Candidate confidence
= Türetilen önerinin doğruluğuna ilişkin çıkarım gücü

Evidence trust.data_class
= Kaynağın Core policy tarafından atanmış güven sınıfı
```

`confidence: high`, kaynağa talimat verme veya işlem yaptırma yetkisi vermez. Candidate, `derived_from` ile Evidence’a bağlanır; trust sınıfını kopyalayıp yeniden belirlemez. Örneğin güvenilmeyen bir mailden tarih yüksek confidence ile çıkarılabilir, ancak Evidence `trust.data_class: untrusted_external` kalır ve `instruction_authority: none` değişmez.

---

# 26. Çapraz-domain örnek

Bir PDF yüklenir:

```text
PDF
↓
Document System içeriği ve kaynak konumunu çıkarır
↓
Mevcut Evidence sözleşmesi/policy kodu kaynak, tarih ve konum bağını doğrular
↓
Evidence: "3 Kasım Matematik sınavı"
↓
Candidate
↓
Study öğrenme anlamını sınıflandırır:
course = Matematik
topic ilişkileri
↓
Organizer Event / Reminder adayları
```

Kullanıcı onaylarsa:

```text
Organizer
├─ Event
└─ Reminder
```

oluşabilir.

Dış takvime yazılacaksa:

```text
Organizer
↓
Core
↓
Permission Gate
↓
Communication
↓
Google / Outlook
↓
Receipt
↓
CalendarLink
```

---

# 27. Domain sınırları

```text
DOCUMENT
= Kaynaktan bilgi çıkarır.

STUDY
= Öğrenme anlamını yönetir.

ORGANIZER
= Kişisel görev/zaman/not/plan/proje kayıtlarını yönetir.

COMMUNICATION
= Dış iletişim ve takvim sağlayıcılarıyla konuşur.

CORE
= Domain'ler arası yürütmeyi yönetir.
```

---

# 28. Değişmez Organizer kuralları

1. Organizer ayrı execution engine değildir.
2. Organizer Task ile Core Job aynı nesne değildir.
3. Event ile Reminder aynı nesne değildir.
4. Event ile External Calendar Event aynı nesne değildir.
5. CalendarLink yalnız iki kayıt arasındaki bağlantıdır.
6. Journal, Note veya Daily Briefing ile aynı nesne değildir.
7. Journal yalnız açık kullanıcı niyetiyle kalıcılaştırılır.
8. Journal kişi sınırını aşamaz.
9. Journal varsayılan olarak özel veridir.
10. Organizer provenance için yalnız `derived_from` kullanır.
11. Organizer varlıkları ortak envelope paylaşır ama tek dev kayıt oluşturmaz.
12. Routine gelecekteki yan etkili işlemlere genel izin vermez.
13. Her Routine tetiklemesinde capability ve permission yeniden doğrulanır.
14. Plan önceliği deterministik policy ile hesaplanır.
15. Model planı açıklayabilir ancak tek başına kalıcı zamanı/önceliği değiştiremez.
16. Mail-derived proje/görev/tarih bilgisi önce Candidate olur.
17. Global eski worktrack verileri bütün kullanıcılara kopyalanmaz.
18. Calendar senkronizasyonunda provider version kontrol edilir.
19. Dış değişiklik yerel kaydın üzerine sessizce yazılmaz.
20. Eski Organizer verileri doğrulanmış migration tamamlanmadan silinmez veya terk edilmez.
21. Legacy ID eşlemesi korunur.
22. Yeni Organizer capability'leri ortak Capability Manifest'i kullanır.
23. Domain koordinasyonu Core üzerinden yürür.
24. Task bağımlılık invariant’larını kod uygular; model yalnız önerir.
25. Zamanlı Event için başlangıç, bitiş ve IANA timezone doğrulaması zorunludur.
26. Her Reminder occurrence deterministik `trigger_id` ile en fazla bir kez teslim edilir.
27. `external_write` kesin dış hedef, idempotency ve reconciliation olmadan çalışmaz.
28. Evidence Policy ayrı bir domain veya motor değildir; ortak Evidence sözleşmesinin doğrulama kuralıdır.
29. Organizer varlıklarının ortak envelope alanları tek validation tabanından gelir.
30. Candidate confidence, Evidence trust veya instruction authority yerine geçmez.
31. Legacy ve yeni Organizer depolarına aynı mantıksal kayıt için çift yazılmaz; write authority tek ve atomik biçimde devredilir.

---

# 29. Nihai Organizer görünümü

```text
                    ORGANIZER SYSTEM
                           │
       ┌───────────────────┼───────────────────┐
       │                   │                   │
      TASK                EVENT               NOTE
       │                   │                   │
       │               REMINDER             JOURNAL
       │
    PROJECT
       │
   MILESTONE
       │
       └──────────── PLAN ─────────── ROUTINE

                           │
                     CALENDAR LINK
                           │
                           v
                 COMMUNICATION SYSTEM
                           │
                    GOOGLE / OUTLOOK
```

Organizer’ın eklenmesiyle Jarvis’te artık şu sınırlar netleşir:

```text
Core
= yürütme

Organizer
= kişisel organizasyon

Study
= öğrenme

Document
= kaynak anlama

Communication
= dış servis bağlantıları

PC
= gerçek Windows işlemleri
```