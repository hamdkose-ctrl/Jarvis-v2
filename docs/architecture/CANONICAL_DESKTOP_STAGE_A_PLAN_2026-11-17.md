# Canonical Masaüstü Aşama A Planı — 17 Kasım 2026

## Karar

Hamdi'nin onayladığı Karar 2 (PC/Browser canonical entegrasyonu) Seçenek 1, sıra A → B → C'nin A aşaması: interaktif masaüstü görevi canonical Core+Scheduler yaşam döngüsüne tek PR ile bağlanır. Gerçek fiziksel operasyon mevcut `desktop_agent`/`desktop_uia` motorunda kalır; canonical taraf yalnız admission, onay, lease ve CAS sahipliğini alır. İkinci bir motor yazılmaz; `PC görevi` açık protokolü ve sync goal lane bu aşamada değişmez.

## Değişiklik

- Yeni canonical yetenek `task.desktop`: `task_tools.CATALOG` (target ≤200, goal ≤2000, opsiyonel answer; replay_safe=False), `capability_manifest._TASK_POLICIES` (physical / physical_effect / ask_required / conditional / required — `goal.desktop` ile aynı zarf).
- Plan admission: `goal_plan_gate._SCHEDULED_EFFECTS` += task.desktop; desktop effect node yalnız bağımlılıksız kök olabilir.
- Lane: `canonical_scheduler_lane._SUPPORTED`/`_EFFECTS` += task.desktop; effect tek başına offer edilir; çalışan başka adımla yarışmaz.
- Kaynak: `scheduler_resource_gate._effect_keys` desktop → `pc_desktop` lease anahtarı (read-only pilot gözlemle aynı fiziksel kimlik); `effect_worker` allowlist += task.desktop. Motor ayrıca kendi OS claim'ini (`physical-desktop-claims`) ve `_BUSY` kilidini korur.
- Dispatch: ilk tur BRAIN-08 deseninde prepare checkpoint'tir — `runtime_prepare_approval` + `goal_approval` kartı (uygulama/hedef metni) kullanıcı tarafından `hedef onayla <job> <control>` ile tüketilmeden hiçbir fiziksel eylem başlamaz. Onaydan sonra tek yürütücü Scheduler'dır.
- Duraklama turu: motor approval/consent/pending_effect durumunda WorkerResult ÜRETMEZ; dispatch sonucu `state='approval'` + `desktop_id` ise adım journal'da yeni bir Core onay kartına bağlanır (`_canonical_desktop_id`), `waiting`/`approval_at`/`blocker` yazılır ve False dönülür. CAS'e gitmez, başarısızlık fence'i yemez.
- Sürdürme: tüketilmiş onaydan sonra aynı attempt (1) ve aynı command fence ile devam eder. `approve_effect` ve `ready_offers` yalnız `_canonical_desktop_id` bağlı desktop adımı için açılır; diğer tüm başlamış adımların "tekrar onaylanamaz/yeniden offer edilmez" fence'i aynen durur. `record_intent` replay yasağı korunur: aynı exact fence'in intent'i zaten durable ise yeniden kaydedilmez, farklı girdi/attempt EffectReplayBlocked kalır.
- Adaptör: `goal_tools` desktop dalı `identity['_canonical_desktop_resume']` bağını owner+target+goal+id eşitliğiyle doğrular; engine approval → `run(approval=native approval id)`, consent → `PC izin ver`, pending_effect → `run`; question/paused → blocked (bu aşamada canonical cevap kanalı yok). Done turu doğrulanmış history + `desktop_uia` receipt + digest ister; receipt `effect_journal`'a succeeded yazılır ve `worker_result_commit` bunu zorunlu görür.
- Restart audit: duraklama kartı (approval + attempts=1 + started + bağlı desktop id) `approval_pending` olarak tanınır; çalışırken çökme `started_unknown` fence'inde kalır — belirsiz fiziksel eylem asla otomatik tekrarlanmaz.

## Kanıt

- `tests/test_canonical_desktop_stage_a.py` (22 test): manifest/lane/plan-gate/lease admission, girdi sınırları, resume bağ uyuşmazlığı, legacy/canonical resume çakışması, consent/approval/pending_effect turları, question→blocked, done→receipt+digest doğrulaması, tur sırasında görev değişimi, taze başlangıç protokolü.
- Komşu canonical süitler (effectful scheduler, phase4b, agents index) aynı koşuda yeşil: 44 test OK.
- Canlı kabul: gerçek PC'de fiziksel Windows kabulü (Hamdi'nin PC gecesi) — exact-SHA CI + PC watcher ek olarak beklenir; bu PR tek başına "bitti" değildir (Bitti kuralı: eski sync yürütme dalı ancak Aşama C parite kanıtından sonra kalkar).
