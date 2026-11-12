# JARVIS-v2 — BRAIN-03 final semantic authority inventory (taslak)
13 Kasım 2026 · Issue #545 · hedef: tek PR

**Durum: AÇIK, BİTTİ DEĞİL.** Bu sayfa, repo-main
`c910d46214bcf500078b8a640b0ea3d9a5baa188` üzerindeki
`tests/test_brain_b3_second_semantic_authority.py` içindeki
`RAW_SEMANTIC_DOORS` envanterini sınıflandırır.
Envanter, 32 pinli simge içerir: 10 kayıt boş caller kümesi, 22 kayıt
en az bir caller içerir. Bu sayılar mevcut **testte pinli değerlerdir**;
test bu dalda henüz çalıştırılmadı. Caller-set eşitliği / import-alias
AST taraması yalnız CI veya gerçek test koşumundan sonra doğrulanabilir.

Bu tablo *simgeleri* üç role ayırır. Bir fonksiyon iki role sahipse
sorumlulukları bölmeden ve parity kazanmadan bütün fonksiyonu silmek yasaktır.

| Eski kapı | Pinli canlı çağıran | Rol / karar | Yeni semantic owner + Core sınırı | Kalan |
|---|---:|---|---|---|
| `messaging.is_whatsapp_message` | 0 | RETIRED_CALLER_ZERO | `message.send` Core | AST recheck |
| `messaging.quick_parse` | 0 | RETIRED_CALLER_ZERO | `message.send` Core | AST recheck |
| `messaging.extract` | 0 | RETIRED_CALLER_ZERO | `message.send` Core | AST recheck |
| `_contact_command` | 0 | RETIRED_CALLER_ZERO | `contacts.manage` Core | AST recheck |
| `learning.handle` | 0 | RETIRED_CALLER_ZERO | `learning.manage` Core | AST recheck |
| `_file_command` | 4 | KEEP_EXACT_OR_STATE + RETIRE_SEMANTIC_OWNER | quoted UI exact / `files.read` + `files.mutate`; Workbench unresolved | Workbench parity/removal |
| `system_control.windows_settings` | 0 | RETIRED_CALLER_ZERO | `windows.settings.open` Core | AST recheck |
| `selfctl.handle` | 0 | RETIRED_CALLER_ZERO | `jarvis.selfctl` Core | AST recheck |
| `_user_command` | 0 | RETIRED_CALLER_ZERO | typed profile/macro | AST recheck |
| `_user_controls` | 2 | RETIRE_SEMANTIC_OWNER + KEEP_EXECUTOR | sharing/voice selection unplanned only; typed accepted plan fenced | semantic parity and raw removal |
| `_planner_command` | 3 | RETIRE_SEMANTIC_OWNER + KEEP_EXECUTOR | notes/reminder typed Core; pending exact | note/calendar edit + agenda parity/removal |
| `_macro_teach` | 0 | RETIRED_CALLER_ZERO | `macro.teach` Core | AST recheck |
| `_macro_manage` | 0 | RETIRED_CALLER_ZERO | `macro.manage` Core | AST recheck |
| `_macro_run` | 2 | KEEP_EXACT_OR_STATE + KEEP_EXECUTOR | saved owner exact trigger allowed for typed plan | fuzzy aliases unplanned only / parity |
| `_extra_commands` | 1 | RETIRE_SEMANTIC_OWNER + KEEP_EXECUTOR arms | typed Core plan fenced; unmapped domain cascade still live | migrate every arm |
| `job_front.wants` | 1 | KEEP_EXACT_OR_STATE | bounded Job state | verify pending/Goal isolation |
| `goal_executor.handle` | 1 | KEEP_EXACT_OR_STATE | Goal Resolver / goal state | verify exact pending |
| `continue_app` | 1 | KEEP_EXACT_OR_STATE | pending app selection | verify owner/TTL |
| `_study_intent` | 1 | RETIRE_SEMANTIC_OWNER + KEEP_EXACT_OR_STATE | new study intent needs Brain/Core, active lesson stays bounded | Hoca parity |
| `hoca.handle` | 1 | RETIRE_SEMANTIC_OWNER + KEEP_EXECUTOR | lesson start vs active lesson answer | Hoca parity |
| `plugins.handle` | 1 | KEEP_EXACT_OR_STATE + RETIRE_SEMANTIC_OWNER | developer-registered capability, no self-install | prove exact triggers & retire global scan |
| `handoff.handle` | 1 | RETIRE_SEMANTIC_OWNER + KEEP_EXECUTOR | work/home handoff typed domain | safe target/intent |
| `browser.handle` | 1 | RETIRE_SEMANTIC_OWNER + KEEP_EXECUTOR | browser action typed Core + permissions | privacy/open URL parity |
| `tasks.handle` | 1 | RETIRE_SEMANTIC_OWNER + KEEP_EXECUTOR | task list typed capability | target/CRUD parity |
| `kb.handle` | 1 | RETIRE_SEMANTIC_OWNER + KEEP_EXECUTOR | knowledge search typed capability | query/source parity |
| `filesend.handle` | 1 | KEEP_EXACT_OR_STATE + RETIRE_SEMANTIC_OWNER | owner-bound file send + pending | ambiguous target & permission |
| `worktrack.handle` | 1 | RETIRE_SEMANTIC_OWNER + KEEP_EXECUTOR | work project typed capability | write/approval parity |
| `files.handle` | 1 | KEEP_EXECUTOR + RETIRE_SEMANTIC_OWNER | files action typed Core | raw operation parser retirement |
| `media.handle` | 1 | KEEP_EXECUTOR + RETIRE_SEMANTIC_OWNER | `pc.media.action` covers controls, search/play parity open | provider permission |
| `_mail_handle` | 1 | KEEP_EXECUTOR + RETIRE_SEMANTIC_OWNER | mail typed capability | provider/permission & send parity |
| `notify.handle` | 1 | KEEP_EXECUTOR + RETIRE_SEMANTIC_OWNER | notification rules typed Core | scheduling/owner parity |
| `_screen_ocr` | 1 | KEEP_EXECUTOR | OCR read versus OCR-to-note are different Core effects | typed provenance / permissions |

## İlk merkezi sınır — henüz final cutover değil

`brain_entry.prepare → core_plan → handoff → brain_precedence.claim`
zincirinde **plan varlığı**, ham
`_user_controls`, `_planner_command` ve
`_extra_commands` için ikinci semantik etki hakkı vermez.
Önceden intent bazlı 7 istisna ve 4 kontrol istisnası bulunan
kodda bu karar şimdi *genel veri çiti* olarak uygulanır.
İstisnalar: explicit tırnaklı UI, tam kayıtlı makro tetikleyicisi,
Core-bağlı reminder note-add. State/Fast ve plansız eski domain
isteklerinin sahipliği değişmez.

Görsel yeniden-deneme komutu daha önce `_RETRY.search` nedeniyle
`yeniden dene demedim` gibi metinlerden de dış worker başlatabiliyordu.
Tam sözcük/cümle eşleşmesi ve belirsiz iki kaynak için clarifying
response sınırı kondu. Dış görsel worker ve Cloudflare yapılandırması
değişmedi.

## Bitti kuralı ve açık kapılar

| Koşul | Durum |
|---|---|
| 1. Sözleşme / arayüz | KISMİ: typed-plan fence kuralı yazıldı, tüm domain manifestleri yok |
| 2. Eski semantic code göçü | AÇIK: 22 canlı pinned caller'ın tümünde parity yok |
| 3. Gerçek kullanıcı akışı | KISMİ: `prepare/handoff` mevcut üretim yoluna bağlı; yeni regresyon testleri henüz çalışmadı |
| 4. Gereksiz legacy'nin fiziksel silinmesi | AÇIK: `_extra_commands`, planner ve diğer eski parser'lar duruyor |

**BRAIN-03 #545 kapatılamaz.** Bu tek PR'a eklenmesi gereken işler:
planner/takvim/not işlemleri, cascade'in 16 kolu, Workbench referans
takibi, uzman ajan/Hoca pending girişleri, paylaşım/kamera/ses sahipliği,
model accepted-chat/rejection/fallback ve çağıran-sıfır temizliği.
Riskli domain effect'lerini yalnız dosya sayısı azalsın diye silme.

Kabul: aynı PR HEAD SHA üzerinde Windows CI completed/success + gerçek
PC watcher Genel/Validation passed; ayrıca canlı model Full holdout
UNMEASURED ise PASS iddia edilmez. Henüz hiçbir yeni kabul yapılmadı.


### Bu tek PR içindeki ilave gerçek kod göçü (henüz CI/PC kabulü yok)

- `screen.text` → Core `screen_text`: `read|copy|error_note` enum'unu Core doğrular; OCR/clipboard/profil notu yürütmesi `engine_intents` üzerinden mevcut effect sahibine bağlandı; ekran gizlilik kontrolü ve OCR sonrası iptal çiti var.
- `device.share` → `share_control`: `screen|camera|stop` enum'u mevcut `engine_output.set_share` privacy/Vision/UI/audit yoluna bağlıdır.
- `voice.rate` → `voice_rate`: `faster|slower` sadece mevcut `engine_context.set_profile_rate` ve `voice_runtime` ile uygulanır, ikinci ses kimliği yazıcısı yok.
- `brief.read` → `daily_brief`: var olan kişisel günlük özet okuma adaptörü.
- `workbench.followup` → `workbench_followup`: son tablo işinin owner-bağlı SHA-256 snapshot kimliği canonical `ActiveContext`te salt-okunur sunulur. Core yalnız `revise` ve `excel|word|pdf` onaylı biçimini kabul eder; mevcut `workbench.handle` çalışmadan önce snapshot/owner ve `nxapi.allowed` tekrar doğrulanır. Son tablonun path'i model önerisinin yetki alanı değildir.
- `study.read` → `study_read`: ders programı ve konu odağı mevcut `studyexam` worker'ı üzerinde ortak `study_read` effect sahibiyle tipli okuma. Hoca aktif ders devamı ve `_study_intent` model başarısızlığı fallback'i korunur.
- Birincil model CHAT kararı artık `MODEL_CHAT_DECIDED` kapalı protokol izi taşır; `_use_existing_handler` bu turu ham kamera/not/cascade seçicilerine geri bırakmaz. Model yanıtı yoksa iz yoktur ve mevcut deterministik fallback korunur. Mevcut exact `_FILE_CMD`, explicit PC/workflow, yayın/güncelleme protokolleri kendi bounded sahibinde kalır.
- **Fiziksel emeklilik:** `modules/engine_context.py` içindeki caller-zero `_user_command = _user_controls` uyumluluk takma adı kaldırıldı. Not/takvim, OCR'ın eski raw fallback'i, Workbench'in eski serbest followup'ı, Hoca, `_extra_commands` kolları HENÜZ fiziksel silinmedi.
- **Regresyonlar:** `tests/test_brain_03_typed_domain_wiring.py`, `tests/test_brain_03_final_authority_cutover.py`, `tests/test_brain_primary_understanding.py` ve mevcut caller guard güncellendi. Testler, full Windows CI, gerçek PC watcher ve canlı model Full holdout bu dalın yeni SHA'sı için **henüz çalıştırılmadı**. Kabul edilmemiş hiçbir sonucu PASS sayma.

**Kalan BRAIN-03 blokları:** not/takvim edit/delete raw authority; `_extra_commands` domain'lerinin tamamında canonical worker önkoşul ve fallback paritesi; Workbench eski raw takip yolunun caller-zero olması; Hoca başlatma/uzman ajan capability migration; kamera/ses seçimi ve model-yok/negation gerçek Full holdout; tüm kodun fiziksel temizliği. Dört Bitti koşulundan 2 ve 4 açık, 3 test/ci/PC ile henüz kanıtlanmadı; #545 **AÇIK**.
