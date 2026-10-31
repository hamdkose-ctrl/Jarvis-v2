# Jarvis Yol Haritası — Hasat Listesi Yapım Sırası

Tarih: 25 Ekim 2026 · Hamdi · Durum güncellemesi: 26 Ekim 2026 (main 5cae9b9, "bitti" kuralına göre yeniden değerlendirildi) · 28 Ekim 2026 (Faz 1'e #437 model-bağımsız haber hattı maddesi eklendi) · 29 Ekim 2026 (Faz 0 kapanış durumu güncel `main` ve merge edilmiş cutover/guard işleriyle yeniden hizalandı; gerçek-PC cutover + exact-main final acceptance kanıtlarıyla Faz 0 kapatıldı)

## "Bitti" kuralı

Bir madde ya da faz ancak şu dört koşulun **hepsi** sağlanınca "tamamlandı" sayılır:

1. **Sözleşme:** Sözleşme / arayüz yazıldı.
2. **Göç:** Eski kod göçü tamamlandı; eski mantık yeni yapıya taşındı.
3. **Bağlantı:** Yeni kod kullanıcı akışına bağlandı; Jarvis çalışırken gerçekten devreye giriyor (yalnız testten çağrılması yetmez).
4. **Temizlik:** Eski kod / legacy kısım kaldırıldı.

Dördünden biri eksikse faz "kısmi" kalır ve sıradaki faz onun üstüne kurulmaz. PR merge edilmiş olması tek başına "bitti" demek değildir. Eski kod yoksa (tamamen yeni yetenek) 2. ve 4. koşul "yok, gerekmiyor" diye açıkça yazılır; yalnız belge PR'larında koşul 3 ve 4 uygulanmaz.

İşaretler: ✅ dört koşul da tamam · 🟡 merge edildi ama koşullardan biri eksik (eksik olan yazılı) · 🔄 açık PR var, merge bekliyor · işaretsiz: başlanmadı.

Kısa gösterim: `[1✓ 2✗ 3✗ 4✗]` = sözleşme var, göç / bağlantı / temizlik yok. `–` = o koşul uygulanmaz (taşınacak ya da silinecek eski kod yok), `🟡` = yarım.

Bu sayfa, Hasat Listesi'nin Jarvis-v2 güncel `main` durumuna göre eksik kalan işlerini yapım sırasıyla verir. Bitmiş şeyler yazılmadı. Her maddede ne eklenecek ve şu an ne var yazıyor. Ücretli ya da kart isteyen hiçbir şey listede yok. Her faz bir öncekinin kabul kanıtını ister.

---

## Karar bekleyenler

**Şu an sizden bekleyen karar yok.**

Alınmış kararlar: Faz 9 bölünmesi onaylı, anahtar havuzu yok, MCP/API sunucusu yok, ses tanıma yok, Telegram ve WhatsApp kalıyor, "ben Hasan" profilleri kısıtsız. GoalState RFC'nin dört kararı kabul edildi; canonical-authority/cutover mekanizmaları merge edildi ve gerçek-PC legacy promotion + exact-main final acceptance kanıtlarıyla Faz 0 kapatıldı. Kapanış kaydı: `docs/architecture/JARVIS_PHASE0_CLOSEOUT_2026-10-29.md`.

---

## Genel sıra

- Faz 0: Aşama 0–4 kapanışı (✅ tamamlandı: gerçek-PC owner taraması, 18/18 canonical promotion, exact-main Architecture Guard, full validation, Windows CI ve watcher acceptance PASS)
- Faz 1: 429 ve Ollama'sız çalışma (🟡 kısmi: provider hata kopyaları #423 ile temizlendi; F-009 strict zero-cost evidence routing kabul bekliyor; #437 model-bağımsız haber hattı açık PR — kod/CI hazır, canlı PC haber kabulü geçti (2 tarihli makale / 2 yayıncı, modelsiz); arayüz durum satırı kabulü bekliyor)
- Faz 2: Zamanlama, olay, hook ve temel muhakeme (🔄 kapanış kabulü bekliyor: canlı akışa bağlandı; bu PR `gateway_hooks.py` ikinci registry/implementation'ını kaldırıp canonical `hooks.py` hattını tek authority yapıyor; F-011 #431 acceptance kaydı ayrıca korunuyor)
- Faz 3: Envanter ve Finance sözleşmesi (🟡 kısmi: Finance sözleşmesi var, 3-B..3-F göçü yapılmadı)
- Faz 4: Yalnız okuma yapan worker'lar (🟡 kısmi: 7/7 sözleşme merge edildi, hiçbiri akışa bağlı değil)
- Faz 5: Güvenilirlik ve gözlem
- Faz 6: Sandbox, skill, kod ajanı
- Faz 7: Alt-ajan ve Kanban
- Faz 8: MCP istemcisi ve güvenli eklenti
- Faz 9: Bilgisayar kontrolü
- Faz 10: Dışarıya etki eden işler
- Faz 11: Profiller, hafıza, context
- Faz 12: Düşük öncelikli alanlar

---

## Faz 0 — Aşama 0–4 kapanışı

**Durum: ✅ tamamlandı `[1✓ 2✓ 3✓ 4✓]`. Canonical GoalState authority/cutover, UI/Core authority sınırı, effect/crash-recovery ve Decision Authority guard hattı merge edilmiş; gerçek Windows PC cutover ve exact merged-main final acceptance kanıtları alınmıştır. Kapanış kaydı: `docs/architecture/JARVIS_PHASE0_CLOSEOUT_2026-10-29.md`.**
Kanıt: PR=#449; SHA=2da471412a53d275659d2f82ac91f2558478c0e9; Contract=#349; Migration=#422; Wiring=#447; Acceptance=watcher-pass@2da471412a53d275659d2f82ac91f2558478c0e9; Cleanup=verified

- **Canonical authority / legacy write stop (#349/#385):** Yeni işler canonical authority ile açılır; canonical-authority işlerde legacy `<id>.json` lifecycle yazımı durmuştur.
- **Cutover / promotion (#348/#422):** Gerçek PC owner verisi salt-okunur planla tarandı; 18 uyumlu legacy-authority aday mevcut #422 operatör-onaylı hattıyla 18/18 canonical'a promote edildi. Son planda blocker, backfill veya promotion adayı kalmadı.
- **UI/Core authority (#441/#444):** `team_control` ve `team_verify` authority'si canonical Core servislere taşındı; `ARCH-006` regresyonu blocker yapar.
- **Receipt/crash recovery (#445):** Receipt-required effect doğrulanmış receipt olmadan success commit değildir; blind retry yoktur.
- **Decision Authority wrapper guard (#447):** `worker_result_hook.execute(...)` yalnız durable `specialist_orchestrator.py` sınırından çağrılabilir; bypass `ARCH-007` blocker'dır.
- **Final exact-main acceptance:** `main@2da471412a53d275659d2f82ac91f2558478c0e9` üzerinde Architecture Guard PASS; full `modules.validation` `3391 test / 3 skip` PASS; Windows CI #910 SUCCESS; gerçek-PC watcher `STATUS=passed` ve exact-SHA raporu `%LOCALAPPDATA%\Jarvis\pc-acceptance\reports\2da471412a53d275659d2f82ac91f2558478c0e9.json` altında arşivlendi.
- **#347 compatibility bridge:** Faz 0 kapanışını bloklamaz. Legacy authority/write yolu canonical işlerde kapalıdır; gerçek-PC promotion adayı kalmadığı için köprünün fiziksel silinmesi daha sonra ayrı ve kanıtlı cleanup olarak değerlendirilebilir. Bu bounded safety shim ikinci authority değildir ve `[4✓]` kararını geri açmaz.
- **F-003 çekirdek ayrımı (0–4 kararı):** Memory ≠ Task State ≠ Context için 0–4'te yeni capability PR'ı açılmaz. Memory davranış/context girdisidir, session konuşma metadata'sıdır, cron zamanlama ifadesidir; kendi başlarına GoalState lifecycle/completion/permission authority yaratamazlar. Mevcut Core/GoalState writer ve execution guard sınırları korunur; ayrıntılı memory/context lifecycle Faz 11'dedir.

---

## Faz 1 — 429 ve Ollama'sız çalışma

**Durum: 🔄 kısmi `[1✓ 2✓ 3✓ 4🔄]`. Provider sınıflandırma temizliği #423 ile `model_health.py` ve `image_gen.py` tarafında ortak `failure_policy` hattına taşındı. F-009 bu fazın açık dikey işidir: `cloud_free_confirmed` tek başına otomatik cloud izni sayılmayacak; exact provider/model için provenance'lı free-tier evidence, TTL, eligibility, quota durumu ve hard-stop guarantee geçerli değilse strict zero-cost router fail-closed kalacak. CI + gerçek PC watcher kabulü gelmeden F-009 tamamlandı sayılmaz. İş PC'sinde Ollama'sız gerçek kabul ve gerçek LM Studio / Groq denemesi ayrıca bekliyor. #437 ile tarihli haber isteği kota sırasını beklerken iş kaydı açılıyor ve keşif/doğrulama/teslim modelsiz yürüyor; bu fazın haber kolu kod+CI aşamasında, canlı PC kabulü bekliyor; `news_recovery` sohbet teslimi artık haber hattının doğruladığı adresleri mühürlüyor.**

Ağ ve model hataları net biçimde yönetilir; Ollama yoksa ya da kota doluysa asistan yine çalışır. İstikrar yoksa zamanlama veya worker eklemek anlamsız.

- 🟡 (#350) `[1✓ 2✓ 3✓ 4✗]` 429, kota, ağ, kimlik doğrulama ve yerel model yokluğu kullanıcıya ayrı ve anlaşılır nedenlerle gösterilecek; kalıcı kota hatası geçici hatadan ayrılacak. Şu an hata sınıflandırması ve bekleme var, ama bazı hedeflerde ham hata gidiyor.
- 🔄 (F-009) `[1✓ 2✓ 3✓ 4🔄]` Otomatik cloud rota yalnız exact provider/model için doğrulanmış, süresi geçmemiş, uygun, hard-stop garantili ve bilinen kota tükenmemiş free-tier evidence ile açılacak. Evidence yok/stale/unknown ise allow değil; ücretli fallback yapılmaz. `usage_meter` limit gözlemi kanıt yerine geçmez; mevcut cooldown/fallback korunur.
- 🔄 (Provider P0-1 / `provider-routing-policy-v1`) `[1✓ 2✗ 3✗ 4✗]` PUBLIC/PRIVATE provenance çekirdeği: `modules/privacy_sources.py` tek yetkilidir. Varsayılan PRIVATE; etiketsiz/bilinmeyen/malformed/sahte veri PRIVATE; PUBLIC yalnız `PUBLIC_SOURCE_ALLOWLIST` (`web_search`, `news_pipeline`, `public_page_reader`) ve tek helper `mark_public` ile üretilir, kaynak kendi kendine PUBLIC diyemez; PUBLIC+PRIVATE her zaman PRIVATE ve geri yükseltme API'si yok (`dataclasses.replace`, elle kurulan etiket, alt sınıf, dict, pickle PUBLIC üretemez). Garanti kural ve test düzeyindedir; süreç içi kodun `_ISSUER`'a erişmesi kapsam dışıdır. Etiket kaynağı kanıtlar, içeriği değil: üretici çıktısı P0-3'te doğrudan bağlama noktasında etiketlenecek; zaten PRIVATE olan içeriğe `mark_public` uygulamak tasarım kuralıyla yasak. **YAPILMADI:** henüz hiçbir istek yolu bu modülü çağırmıyor; evidence bundle/Cloudflare (P0-2), Router tek authority, `llm.py` cross-provider fallback silme ve OpenRouter silme (P0-3), acceptance (P0-4) sırada. Eski seçim yetkisi (`llm._send`, `smart_router.selection`) bu PR'da değişmedi.
- 🔄 (Provider P0-2 / `provider-routing-policy-v1`) `[1✓ 2✗ 3✗ 4✗]` Provider gizlilik evidence bundle'ı: `modules/provider_privacy.py` Groq, Cloudflare ve Gemini için eğitimde kullanım, saklama, izinli rota, resmi `source_url`, `verified_at`/`expires_at` (2026-11-30) tutar; kullanıcı/araç yazamaz. `smart_router._evidence_gate` artık iki ayrı kanıt ister: bu bundle (süresi geçmiş, kaynak adresi boş, `trains_on_data` bilinmiyor, listede yok, NVIDIA → fail-closed; eğitimde kullanabilen sağlayıcı (Gemini) için `route` zorunlu ve yalnız `PUBLIC_RESEARCH`; rotasız çağrı reddedilir. Rota kavramı olmayan eski `selection`/`status` çağrıları bugünkü davranışı korumak için geçici `_LEGACY_ROUTE = PUBLIC_RESEARCH` verir, P0-3 gerçek rota sınıfıyla değiştirir) ve mevcut kullanıcı/model free-tier satırı. Ayrı ikinci katalog yok: satır şeması değişmedi, gizlilik gerçekleri tek yerde. Zincirler (`PUBLIC_RESEARCH` Gemini→Groq→Cloudflare→Ollama, `PRIVATE_GENERAL` Groq→Cloudflare→Ollama) yalnız veri olarak tanımlı. `modules/cloudflare_chat.py` Workers AI metin taşıyıcısıdır (aynı kullanıcıya özel hesap/token, tipli hatalar, seçim/yedekleme yetkisi yok). **YAPILMADI:** Router henüz bu zincirleri ve `route` bilgisini kullanmıyor, Cloudflare sohbet zincirine bağlı değil, `llm._send` / `smart_router.selection` eski yetkisi ve OpenRouter yolu duruyor (P0-3). Bundle 2026-11-30'da süresi dolunca tüm bulut sağlayıcıları kapanır; yenilemek bilinçli bir kod değişikliğidir. OpenRouter için bundle kaydı yoktur (P0-3'te silinir).
- 🔄 (Provider P0-3a / `provider-routing-policy-v1`) `[1✓ 2✓ 3✗ 4🔄]` OpenRouter koddan, web arayüzünden, rehberlerden ve yapılandırmadan tamamen silindi (Hamdi kararı): `smart_router.openrouter`/`api_key`/`_free_emergency` ve acil rota, `llm._send`/`_ask_image` OpenRouter dalları, izinli sağlayıcı kümeleri, UI kartı ve `routersave`/`routerdelete`, `web_models.smart_router_save` anahtar/model parametreleri. Eski kullanıcı verisi: router state'ini okurken bilinmeyen anahtarlar (OpenRouter `key`, `openrouter_model`) ve zincir dışı evidence satırları diskten silinir; kayıtlı `provider=openrouter` kullanıcı `auto` politikasına düşer; `set_provider('openrouter')` ValueError. Statik test kod/web/config'te sıfır OpenRouter referansı doğrular (tarihsel `docs/` hariç). **YAPILMADI:** Router'ın zincirleri ve route class'ı kullanması, `llm._send` içindeki Groq→Gemini / Ollama→Gemini / `_after_gemini` cross-provider fallback'lerinin silinmesi, `embed`/STT/görsel/Live yolları (P0-3b..): bu PR'da eski seçim yetkisi duruyor, P0 4. şartı açık.
- 🔄 (stale Ollama model acceptance düzeltmesi) Stale local-model tercihi artık kurulu Ollama modelini engellemez; runtime yalnız gerçekten kurulu modele bağlanır. Kullanıcı tercihi diskte korunur; kurulu değilse `ollama_models()` listesindeki deterministik modele düşülür. Exact-head CI + gerçek PC stale-selection acceptance bekleniyor; F-009 yeniden açılmaz.
- ✅ (#350) `[1✓ 2✓ 3✓ 4✓]` Sınırlı yeniden deneme ve artan bekleme (backoff) eklenecek. Şu an bekleme var, backoff yok.
- 🟡 (#352) `[1✓ 2✓ 3✓ 4–]` Ollama kurulu değilken modelsiz kısmın doğrulanmış teslimi haber ve finans dışındaki hedeflere de yayılacak. Haber ve finans için modelsiz yol var. İş PC'sinde gerçek kabul gerekiyor; kabul gelmeden ✅ yazılmaz.
- 🔄 (#437) `[1✓ 2🟡 3✓ 4🟡]` Haber bulma / doğrulama / teslim yetkisi model sağlayıcılarından bağımsız olacak: `modules/news_pipeline.py` kota sırası ve Ollama yokluğunda keşif (`publisher_news` kataloğu + `domain_tools.headlines`), tarih (`research_evidence.article` ile `published_at`/`date_status`), kanıt (`model_free_news.quotes`, farklı-host `independent_candidates`) ve deterministik raporu modelsiz yürütür; `news_status` ile `model_synthesis_status` ayrılır ve model yokluğu haber sonucunu asla `unavailable` yapmaz. Keşif ve doğrulama paralel işçileri aktif kullanıcının `llm._key_context` bağlamını kalem başına `copy_context()` kopyasıyla taşır (`service_store.identity` worker içinde de geçer, bağlam yoksa veya başka kullanıcıysa fail-closed kalır); `attach_job` iş özetini ikinci bir tarama yapmadan işin kendi sağlık kaydından üretir; tekil sayfa okumaları yayıncı sırasıyla ve `MAX_ARTICLE_READS` sayısı kadar sınırlı, iki yayıncı doğrulanınca durur. Bağlantı: `goal_executor` kota kapısı artık tarihli haberi durdurmaz, plan hiç yapılamayan haber işinde teslimi pipeline yapar, `news_recovery` sohbet teslimine iş özetini yazar, `render` durum satırını gösterir. Eksik koşullar: `publisher_news.catalog_attempted`/`require_catalog` sayımı geniş isteklerde sıralı tohum adımlarını ister, paralel hat bu sayımın yerine geçmez; `model_synthesis_status` model erişilebilirken çalışan sentez hattına henüz bağlı değil. Kabul ölçütü: Gemini 429 + Groq 429 + Ollama erişilemezken son 7 günün gerçek haberleri kaynak/tarih/link/kanıtla teslim edilir ve yalnız model sentezinin kullanılamadığı açıkça söylenir — haber kısmı bu PC'de ölçüldü: `python -X utf8 -m modules.acceptance_checks --news --skip-suite` → `news_chat_resume: passed` (2 tarihli makale / 2 yayıncı, kota günlüğünde model çağrısı yok, `PermissionError: açık kullanıcı bağlamı gerekli` üretilmedi; düzeltme öncesi aynı kabul 0 makale / 0 yayıncı ile düşüyordu). Kalan canlı işler: arayüz durum satırının gerçek ekranda gösterimi ve sağlayıcılar erişilebilirken sentez kalitesi; testler taşıyıcı taklitleriyle çalışır.
- 🔄 (#439) Canlı normal-Jarvis kabulünde `Türkiye yapay zekâ` isteğine taze ama alakasız İsrail seçim haberi verified oldu ve ilk 8 genel kaynak içinde teknoloji yayıncıları bütçenin dışında kaldı. Kapanış düzeltmesi: `model_free_news` açık konu/kapsamını kanıtta zorunlu tutar; `publisher_news` yeni kaynak eklemeden AI isteğinde DonanımHaber, Webtekno, TÜBİTAK, YTÜ ve Boğaziçi gibi mevcut konu kaynaklarını `MAX_SOURCES` bütçesine öne alır. İki farklı yayıncı şartı `news_pipeline.enough_evidence` ile aynen korunur. Exact-head CI + gerçek PC canlı kabulü geçmeden haber kolu tamam sayılmaz.
- ✅ (#352) `[1✓ 2– 3✓ 4–]` LM Studio ve llama.cpp için yerel uç nokta ayarı eklenecek (opsiyonel). Şu an yalnız Ollama var.
- ✅ (#351) `[1✓ 2✓ 3✓ 4✓]` Kullanıcı başına model seçimi Gemini dışına, yani Groq ve yerel modele genişleyecek; kullanım sınırı gözlemi eklenecek. Şu an yalnız Gemini seçilebiliyor, sayaç karakter bazlı.
- ✅ (#351) `[1✓ 2– 3✓ 4–]` Ücretli sağlayıcıya otomatik geçiş yapılmaz.

---

## Faz 2 — Zamanlama, olay, hook ve temel muhakeme

**Durum: 🔄 kapanış kabulü bekliyor. İlk PR'lar (#353–#371) incelemede (incelemeler/faz2_inceleme.md) canlı akışa bağlı çıkmamıştı; #374 bağladı, #380 kaynak takibine abonelik ekledi, #382 webhook tekrar korumasını ekledi. Ölü `modules/proactive.py` silindi. Bu PR ile production consumer'ı olmayan ayrı `gateway_hooks.py` registry/implementation'ı kaldırıldı; gateway observation dahil tek hook registry/dispatch authority `modules/hooks.py`. `shell_hooks.py` Faz 6 sandbox'a kadar bilinçli fail-closed stub olarak kalır ve shell execution vermez. F-011 completion #431 mevcut scheduler heartbeat'ini reuse ederek gerçek günlük briefing tetik noktası ve eksik durum fact'lerini tamamlıyor; exact-head CI + PC acceptance gelmeden PASS sayılmayacak.**

Cron zamanlama, olay aboneliği ve hook altyapısı eklenir. Aynı fazda temel muhakeme de gelir: artı/eksi analizi, dürüst eleştiri, rehberlik ve proaktif öneri. Otomasyon ile düşünen yanıt aynı temele oturduğu için worker'lardan önce buraya düşerler.

- ✅ (#374) `[1✓ 2✓ 3✓ 4✓]` Genel zamanlanmış görev gelecek: cron ifadesi, "şimdi çalıştır", modelsiz betik görevi, her çalıştırmada temiz oturum. Şu an doğal dil zamanı ve kuyruk var, cron ve "şimdi çalıştır" yok.
- 🔄 (F-011 / #431) Mevcut scheduler/runtime hattı üzerinden günlük briefing tetiklenir; startup ve scheduled çağrı aynı `last_brief` / `_BRIEF_RUNNING` owner guard'ını kullanır. `_day_plan()` açık/gecikmiş/bugünkü iş, Gmail/Takvim, handoff ve reconnect bilgisini sağlar; read-only continuity görünümü tamamlanan, approval ve blocked/failed durumlarını kısa fact olarak ekler. Yeni scheduler/state/approval sistemi kurulmaz. Exact-head acceptance bekleniyor.
- ✅ (#374, #380) `[1✓ 2✓ 3✓ 4✓]` RuntimeEvent için kalıcı abonelik kurulacak: kaynak izleyici, olay, tazelik süzgeci, GoalState kanıtı. Şema ve commit hattı var, gerçek üretici yok (Guard uyarısı ARCH-W001).
- ✅ (#374, #382) `[1✓ 2✓ 3✓ 4✓]` Webhook ve olay tetikleri WhatsApp dışına genişleyecek, sonuç birden fazla kanala gidecek. Şu an yalnız WhatsApp webhook'u ve ntfy var.
- 🔄 (#374 + bu cleanup PR) `[1✓ 2– 3✓ 4✓]` Hook sistemi ajan, araç, model, onay, oturum, alt-ajan, Kanban ve gateway observation için canonical `modules/hooks.py` hattını kullanır. Production consumer'ı olmayan `gateway_hooks.py` ikinci registry/implementation'ı kaldırıldı; observer sonucu execution authority değildir. Exact-head CI + PC acceptance bekleniyor.
- ✅ (#374) `[1✓ 2– 3✓ 4–]` Araç öncesi ihlalde işlemi durduran (fail-closed) ortak kapı eklenecek, mevcut `runtime_execution_gate` üstüne.
- 🔄 (#353 + bu cleanup PR) `[1✓ 2– 3✓ 4✓]` Gateway observation canonical `modules/hooks.py` üzerinden yürür; ayrı `GatewayHooks` registry/implementation kalmaz. `shell_hooks.py` Faz 6 sandbox'a kadar fail-closed stub olarak korunur; subprocess/shell execution eklenmez. Exact-head CI + PC acceptance bekleniyor.
- ✅ (#354, #370, #374) `[1✓ 2– 3✓ 4–]` Artı/eksi analizi eklenecek: önemli bir karar veya seçenek söz konusu olduğunda Jarvis seçeneklerin artılarını ve eksilerini sıralayıp gerekçeli öneride bulunacak. Şu an doğrudan cevap veriliyor, yapılandırılmış değerlendirme yok.
- ✅ (#355, #374) `[1✓ 2– 3✓ 4–]` Dürüst eleştiri eklenecek: iş ve hayat konularında "burada şu zayıf çünkü…" denilebilecek; yumuşatma olmadan ama kırıcı olmadan. Şu an yalnız haftalık hedef raporunda (Goals.java) kısmi eleştiri var, genel konuşmada yok.
- ✅ (#357, #374) `[1✓ 2– 3✓ 4–]` Rehberlik ve tavsiye eklenecek: adım adım pratik yol gösterme, hangi seçeneği neden tercih etmeli, risk ve dikkat noktası bildirimi. Şu an Hoca öğrenme tarafında var, genel danışmanlık yok.
- ✅ (#358, #374) `[1✓ 2– 3✓ 4✓]` Proaktif öneri eklenecek (varsayılan açık): ilgili bir konu veya risk görülünce "bunu da düşünebilirsin" ya da "burada dikkat et" diyecek; ayardan kapatılabilir. Şu an yalnız açık takip isteğiyle (monitor) tetikleniyor, genel konuşmada yok.

---

## Faz 3 — Envanter ve Finance sözleşmesi

**Durum: 🟡 kısmi. Envanter belgesi (#360) ✅. Finance yalnız koşul 1'de: `finance_domain.py` ve sözleşme belgesi var ama üretim kodunda hiçbir yerden çağrılmıyor, eski finans mantığı hâlâ `watcher` ve `domain_tools` içinde. 3-B..3-F göç adımları (#362'deki tablo) yapılmadan Finance bitmiş sayılmaz.**

Finance ve envanter ayrı domain sözleşmelerine bağlanır. Worker'ların okuyacağı veri alanları temizlenmeden worker'lar başlayamaz.

- 🟡 (#362) `[1✓ 2✗ 3✗ 4✗]` Finance ayrı domain olarak sözleşmeye bağlanacak: veri, alarm, analiz, kaynak doğrulama dalları ve kod göçü planı. Karar belgesi var, kod hâlâ iletişim tarafında. Salt okuma, para hareketi yok.
  - 3-B `watcher._finance_price` → `finance.quote` (başlanmadı)
  - 3-C `watcher.finance_tick` ve yardımcıları → `finance_alert_tick.py` (başlanmadı)
  - 3-D alarm teslimi Communication'da, ntfy başlığı ayrılır (başlanmadı)
  - 3-E `domain_tools.exchange` → `finance.dated_rate` (başlanmadı)
  - 3-F `domain_tools.csv_analysis` finans kolu → `finance_analysis.csv_summary` (başlanmadı)
- ✅ (#360) `[1✓ belge PR'ı]` 705 maddelik envanter repoya Capability Intake ikinci dalga olarak işlenecek ve Hermes sürüm referansı commit SHA'ya sabitlenecek. Şu an ilk dalga 20 aday var. Yalnız belge PR'ı.

---

## Faz 4 — Yalnız okuma yapan worker'lar

**Durum: 🟡 kısmi `[1✓ 2✗ 3✗ 4✗]`. 4A–4G'nin hepsi merge edildi (#372, #373, #375, #376, #378, #381, #384) ama her PR yalnız yeni bir modül ve testinden oluşuyor. Yedi modülün (`research_providers`, `file_worker_extensions`, `browser_readonly`, `drive_readonly`, `finance_readonly`, `gmail_calendar_readonly`, `computer_worker_contract`) hiçbiri üretim kodundan çağrılmıyor; eski yollar (ör. `finance.py`, `tool_finance.py`, mevcut tarayıcı ve Gmail okuma kodu) olduğu gibi çalışıyor. Sıradaki iş yeni harf açmak değil, her harfi aynı sırayla (4A→4G) göç, bağlantı ve temizlikle kapatmak.**

Salt okuma yapan worker'lar sırayla devreye girer: araştırma, dosya, tarayıcı, Drive, finans, Gmail/Takvim ve PC Worker sözleşmesi. Veri sözleşmesi hazır; yalnız okuma en güvenli başlangıç noktasıdır.

Araştırma zinciri bu sırayla kurulur: arama sağlayıcısı, kaynak sıralama, paralel araştırma, web ve dosyayı birlikte kullanan araştırma, Hoca araştırma döngüsü, konudan sapma kontrolü.

**Sıra kilitli:** Faz bölünmez ama PR sırası kesindir. "Merge edildi" yetmez; bir harf "bitti" kuralının dört koşulunu sağlamadan sonraki faz (Faz 5) açılmaz. Aynı anda tek alan açık olur; bir sonraki harf, önceki harf merge edilmeden başlamaz. Sıra: 4A Araştırma ve Hoca, 4B FileWorker sağlamlaştırma, 4C Tarayıcı salt okuma, 4D Drive salt okuma, 4E Finans salt okuma, 4F Gmail ve Takvim salt okuma genişlemesi, 4G PC Worker temel sözleşmesi.

### 4A — Araştırma ve Hoca

🟡 (#372) `[1✓ 2✗ 3✗ 4✗]` Sözleşme modülü ve testi var; akışa bağlı değil.

- Kart istemeyen arama sağlayıcıları eklenecek: SearXNG, DuckDuckGo, Tavily, Exa, Firecrawl. Arama ile içerik çıkarma ayrı sağlayıcılar olacak. Şu an yalnız doğrudan yayıncı okuma var.
- arXiv ve akademik makale araştırması, kaynaklar arası çelişki karşılaştırması ve kaynak sıralama eklenecek. Şu an hiçbiri yok.
- RSS ve site izleyicisi tam kapsamlı olacak; haftalık haber otomasyonu ve uzun araştırmada bağlam yönetimi eklenecek. Şu an RSS dar, haftalık otomasyon zayıf.
- Kaynak gösterimi biçimi ve konudan kopmama denetimi Hoca dışına yayılacak. Şu an kısmen Hoca'da var.

#### Ek kabul kriterleri — Fable/Claude agent benchmark

- **Kısmen uygulandı (PR #424): güncellik isteğini doğru yönlendirme.**
  - **Kod kanıtı:** `modules/freshness.py:fresh_request` tek karar noktası; router (`_fresh_research_request`) ve `work_modes` (`fresh_external`) buradan beslenir. Tanım kalıbı ("nedir/ne demek/tarihçe") artık yalnız açık tazelik işareti yoksa statik der; `mevcut` ve `bugunku` tazelik işaretleri eklendi. Kararı kilitleyen test: `tests/test_freshness_rule.py::test_explicit_freshness_wins_over_definition_pattern` ve `tests/test_quota_routing.py::test_explicit_freshness_beats_definition_phrasing`.
  - **Beklenen davranış:** "bugün/son/güncel/mevcut/şu an" gibi açık tazelik işareti + konu ("kur/dolar/haber/...") varsa sorgu taze kaynağa (`intent=task`) yönlener; tazelik işareti olmayan sade tanım ("Dolar nedir?", "NVIDIA nedir?") statik/chat kalır ve gereksiz web aramasına zorlanmaz. Kanıtlandı: `Bugünkü dolar kuru nedir?`→task, `Güncel altın fiyatı nedir?`→task; `Dolar nedir?`→chat.
  - **Kabul testi:** Aynı konu için bir güncel ve bir durağan sorgu `test_explicit_freshness_wins_over_definition_pattern` ile assert ediliyor (güncel → taze route, durağan → chat, ağ çağrısı yok).
  - **Routing precedence regresyonu (PR #438):** canlı kullanıcı isteğinde çıktı alanı olarak geçen `tarih` sözcüğü sistem-tarih hızlı yolunu tetiklememeli; tarih/gün hızlı yolu yalnız açık tarih sorularında çalışır. `tests/test_research_day_plan_precedence.py` uzun araştırma cümlesinin research/task yönüne ulaştığını, `_day_plan` çağrılmadığını, gerçek günlük-plan isteklerinin ve startup briefing'in değişmediğini kilitler.
  - **Kalan:** "kural" gibi değişken-bilgi konuları freshness konu listesinde henüz yok; taze kaynak aramasının canlı kanıtı (gerçek yayıncı okuması) bu PR kapsamında ölçülmedi — routing kararı ve statik/taze ayrımı birim düzeyinde doğrulandı.
- **Kısmen uygulandı (PR #432): kaynak çelişkisinde ek doğrulama.**
  - **Kod kanıtı:** `modules/research_providers.py:compare_sources` salt-string set karşılaştırması yerine yapısal semantik modele geçti: iki kaynak yalnız aynı subject+scope+as_of penceresinde ve farklı değer taşıyorsa `conflict`; kelime/zaman/scope farkı `agreement`. `modules/research_providers.py:verify_conflict` gerçek conflict'te anahtarsız `search_public`/`extract_source` hattını yeniden kullanarak en fazla bir bağımsız ek kaynak okur ve `resolved_conflict`/`unresolved_conflict` üretir. Gerçek akış bağlantısı: `modules/research_evidence.py:cross_source_review` writer/rapor teslim hattında (`task_workers.py` `kind=='writer'`) çağrılır; karar kullanıcı raporuna yazılır ve `source_conflict` alanı çıktıya işlenir. Kilitleyen testler: `tests/test_research_conflict.py` (semantic agreement, numeric/categorical conflict, as_of/scope farkı, üçüncü kaynak çözüyor/çözemiyor, determinizm, writer wiring).
  - **Beklenen davranış:** Güvenilir iki kaynak aynı olgu için çelişirse Jarvis ilk sonucu sessizce seçmez; sınırlı ek doğrulama yapar, çözülemeyen çelişkiyi "Kaynak çelişkisi çözülmedi … tek taraf nihai gerçek olarak seçilmedi" notuyla açık bırakır. Uygulandı (testte assert edildi).
  - **Kabul testi:** Enjekte edilmiş iki çelişkili kaynakla writer raporu çalıştırıldığında ek doğrulama çağrısı veya "çözülmedi" sonucu zorunlu; agreement durumunda hiç ağ çağrısı yapılmaz ve rapor metni değişmez — `ResearchOutputWiringTests` ile kanıtlandı.
  - **Kalan:** Yok — producer bağlantısı tamamlandı. Normal research worker tek kaynakta eskisi gibi davranır (kilitli `test_phase4_research_wiring` ve planner tek-kaynak sabitlemesi byte-birebir korunur; çıktıda `source_claims` alanı hiç eklenmez). En az iki bağımsız (farklı host) aday bulunduğunda `modules/research_providers.py:independent_candidates` ile deterministik ve sınırlı (≤3) kaynak seçer, her birinden `modules/research_evidence.py:parse_value_quote` ile yapılandırılmış `{subject,scope,as_of,value,url,evidence}` claim üretir ve yalnız claim üretildiğinde çıktıya `source_claims` olarak ekler (`task_workers.py` `kind=='research'`). Bu claim'ler `cross_source_review`e beslendiğinde conflict/agreement yolu canlı research akışında gerçekten üretilir; erişilemeyen bir kaynak atlanır, tüm araştırmayı düşürmez ve tek tarafa sahte kesinlik verilmez. Kanıt: `tests/test_research_multisource_wiring.py` (13 senaryo — iki bağımsız claim üretimi, aynı değerin farklı ifadeleri→ağ çağrısı yok, gerçek conflict→sınırlı tek ek kaynakla resolved, çözülemeyen→"belirsizdir", tek aday→eski güvenli davranış, erişilemeyen kaynak→diğerleri kullanılır, host-farklı deterministik ≤3 seçim, claim sözleşmesinin yapısal alanları, kaynakta olmayan uydurma değerin reddi ve araştırma worker çıktısının gerçek writer raporuna kadar akışı). Motor/sağlayıcı/router eklenmedi; mevcut `search_public`/`extract_source`/`compare_sources`/`verify_conflict`/`cross_source_review` hattı reuse edildi. Kalan risk: canlı çok-kaynak senaryosunun gerçek PC/model kabulü ayrıca ölçülmeli; çok kaynaklı turda her ek kaynak bir sayfa okuma ve bir yapılandırılmış claim çağrısı üretir (≤3 kaynak, ek doğrulama ≤1), üç ayrı değer bulunursa çelişki taraf seçilmeden belirsiz kalır.

### 4B — FileWorker sağlamlaştırma

🟡 (#373) `[1✓ 2✗ 3✗ 4✗]` Sözleşme modülü ve testi var; akışa bağlı değil.

- Belgeden yapılacak iş, yükümlülük ve son tarih çıkarma eklenecek. Mailden tarihli iş ve ödev parçalama var, genel belge için yok.
- PPTX üretimi, genel dosya yaması ve dosya arama komutu eklenecek. PPTX okuma var, yama yok, arama bilgi tabanıyla sınırlı.
- Dosya güvenliği tamamlanacak: özel dosya türleri (FIFO vb.) koruması, büyük ve minified dosya sınırı, Unicode dosya adı testleri. Boyut sınırı ve yalıtılmış PDF okuma var.

### 4C — Tarayıcı salt okuma

🟡 (#375) `[1✓ 2✗ 3✗ 4✗]` Sözleşme modülü ve testi var; akışa bağlı değil.

- Tarayıcıya erişilebilirlik ağacı tam hâle gelecek; birden çok sekme, indirme ve yükleme, diyalog yönetimi eklenecek. Şu an tek sayfa ve sade okuma var.
- Kayıtlı oturum koruma, kendi şifreli yerel kimlik kasası ve 2FA için insana devretme eklenecek. Ayrı profil ve elle giriş betiği var, kasa yok. Kimlik bilgisi asla modele gitmez.
- Chrome DevTools Protokolü ve gerçek tarayıcı profiline bağlanma eklenecek, görüntü destekli yedek yolla. Şu an yok.

### 4D — Drive salt okuma

🟡 (#376) `[1✓ 2✗ 3✗ 4✗]` Sözleşme modülü ve testi var; akışa bağlı değil.

- Google Drive, Docs ve Sheets okuma entegrasyonu eklenecek. Gmail ve Takvim var, Drive yok.

### 4E — Finans salt okuma

🟡 (#378) `[1✓ 2✗ 3✗ 4✗]` Sözleşme modülü ve testi var; akışa bağlı değil.

- 🟡 F-002 PR 1: doğrulanmış fiyat, kaynak kanıtı, freshness ve en az iki OHLCV mumu varsa mevcut Finance worker üzerinden salt-okunur yapılandırılmış giriş/stop/hedef taslağı üretilir. Seviye yöntemi yalnız son iki mumun gözlenen aralığıdır; veri eksik veya stale ise plan `incomplete` döner ve sayı uydurmaz. Pozisyon boyutu, PASS/BLOCK, kullanıcı onayı, broker ve emir yürütme kapsam dışıdır. PR kabulü bekleniyor; Faz 4E hâlâ 🟡.
- 🟡 F-002 PR 2: planın stale/eksik kanıt, stop, hedef ve risk-getiri görünümü eksiklerini salt-okunur gözlem listesi olarak döndürür. Bu liste PASS/BLOCK, işlem kararı, onay veya yürütme yetkisi vermez. PR kabulü bekleniyor; Faz 4E hâlâ 🟡.
- 🟡 F-002 PR 3: açık hesap değeri, risk bütçesi ve desteklenen birim/step metadata varsa TradePlan + RiskChecklist'ten deterministik pozisyon boyutu ve PASS/BLOCK üretir. Kritik veri yoksa BLOCK; PASS execution permission değildir. PR kabulü bekleniyor; Faz 4E hâlâ 🟡.

- 🟡 F-002 PR 4: yalnız PASS RiskDecision’dan immutable TradeIntent ve owner-bağlı, süreli/revoke edilebilir/tek-kullanımlı JIT approval receipt sözleşmesi üretir. Intent veya plan fingerprint’i, entry/stop/hedef/pozisyon boyutu değişirse onay geçersizdir. ApprovedIntent yürütülebilir emir değildir; broker, order, effect dispatch ve permission grant yoktur. PR kabulü bekleniyor; Faz 4E hâlâ 🟡.
- Günlük fiyat serisi (OHLCV), hisse karşılaştırma ve veri tazelik kontrolü tüm kaynaklara yayılacak. Kaynaklar yalnız TCMB, Frankfurter, CoinGecko Demo, BtcTurk ve yedekli Yahoo. Şu an anlık fiyat var, seri yok.
- Portföy analizi, risk ve varsayım açıklaması, finans kanıt paketi, ticker arama, DCF, benzer şirket ve LBO becerileri ve finans araştırma ajanı eklenecek. Şu an izleme listesi ve alarm var. Yatırım tavsiyesi verilmez.

### 4F — Gmail ve Takvim salt okuma genişlemesi

🟡 (#381) `[1✓ 2✗ 3✗ 4✗]` Sözleşme modülü ve testi var; akışa bağlı değil.

- Gmail konuşma (thread) okuma ve Takvim planlama önerisi genişleyecek. Şu an okuma ve arama var.

#### Planlama saat gösterimi

- Google Takvimden gelen saatli kayıt, plan çıktısında Jarvis'in çalıştığı makinenin saat dilimine ikinci kez çevrilmez; kaynağın takvim duvar saati korunur. Bu yalnız salt-okunur gösterim/eşsizleştirme düzeltmesidir; Google takvim yazımı, yetki veya etkinin kapsamı değişmez. Kanıt: PR #413; test `test_google_event_keeps_calendar_wall_time`.

### 4G — PC Worker temel sözleşmesi (yalnız Core tarafı)
🟡 (#384) `[1✓ 2✗ 3✗ 4✗]` Sözleşme modülü ve testi var; akışa bağlı değil.

- ComputerWorker sınırı tanımlanacak, UIA temel ölçümü ve yetenek / makbuz sözleşmesi yazılacak. 4F merge edildikten sonra açılır. Hesap Makinesi ve Not Defteri pilotu, uygulama izin listesi ve manifest var.

Sınır: FileWorker salt okunurdur. Tek dosya değişikliği `file_ops` işidir, toplu değişiklik PC Worker ile Core'un etki hattından geçer. `desktop_agent` ve `desktop_uia` UIA temeli olarak kalır, genişletilmez. Tarayıcı işi BrowserWorker'ındır.

---

## Faz 5 — Güvenilirlik ve gözlem

**Durum: başlanmadı.**

İzleme kimliği, maliyet ölçümü ve değerlendirme eklenir. Worker'lar aktif; neyin çalıştığını ölçmeden ilerlemek kör uçuştur.

- Ortak izleme kimliği ve ana / alt iş izi gelecek; LLM, araç, onay, API ve oturum izleri tek şemada toplanacak. Şu an istek kimliği, kullanım sayacı ve izin kaydı ayrı ayrı duruyor.
- Gerçek token ve maliyet ölçümü, önbellek isabeti, gecikme ve araç çağrısı sayısı eklenecek. Şu an karakter bazlı sayaç ve ses gecikmesi var.
- OpenTelemetry ve Langfuse benzeri dışa aktarım gelecek, yalnız kendi kurulumunuzda, gizlilik korumalı (opsiyonel). Şu an yok.
- Değerlendirme eklenecek: aynı senaryoyu tekrar koşturma, A/B worker karşılaştırması, hareket kaydı, düşmanca dosya testi, PII duman testi, sağlığın tek ekranda toplanması. JarvisBench v0 ve geniş test seti var.
- Makbuz ve kanıt kapsama oranı ile gerçek ajan benchmark raporu eklenecek. Manifest tablosu var, oran raporu yok.

---

## Faz 6 — Sandbox, skill, kod ajanı

**Durum: başlanmadı.**

Sandbox, skill sistemi ve kod ajanı devreye girer. Kod çalıştırmak ve skill yüklemek izole ortam gerektirdiğinden önceki fazlar hazır olmadan buraya gelinmez.

Bu fazın tüm araçları parolayla korunan geliştirici menüsünün arkasında olur.

- Yalıtılmış çalıştırma ortamı eklenecek: görev ve worker başına ayrı alan, kaynak ve süreç sınırı, ağ çıkışı denetimi, yetki düşürme, temizlik. Önce yerel yalıtım. Şu an yalnız adayı yalıtılmış kopyada derleyip test etme var.
- Gerçek anahtarı sandbox'tan gizleyen kimlik bilgisi vekili ve opak belirteç eklenecek. Şu an yok.
- Docker, SSH ve Singularity arka uçları, riskli betiği gerçek PC'den ayırma ve sandbox sağlık kontrolü eklenecek. Şu an yok.
- Tehlikeli komut tespiti ve yıkıcı komut onayı tüm çalıştırma yollarında ortak olacak; gözetimsiz modda her şey reddedilecek. Şu an onaylı program çalıştırma ve yıkıcı eylem sınıfı yalnız araç tarafında var.
- Skill sistemi eklenecek: oluştur, listele, göster, kur, güncelle, sil; yalnız gerektiğinde bağlama yükleme; betik ve şablon dosyaları; agentskills uyumu. Şu an hiç yok. Önce salt okuma pilotu.
- Skill güvenliği eklenecek: sürüm sabitleme, kaynak kaydı, onay ve fark gösterimi, prompt-injection, veri sızdırma, yıkıcı komut ve tedarik zinciri taraması, işletim sistemi uyumu.
- Harici skill depoları doğrudan alınmayacak, yalnız uyarlanacak; başlangıçta yalnız sizin skill'leriniz çalışacak. Jarvis skill kataloğu ve yetenek eksiğinde skill arama ile insan onaylı kurma eklenecek. Şu an yetenek keşfi ve onaylı araç kaydı var.
- Kullanıcı düzeltmesinden ve başarılı iş akışından skill üretme eklenecek, insan onaylı. Şu an düzeltmeden kural öğrenme var.
- Kod ajanı hattı eklenecek: genel terminal, arka plan süreç yöneticisi, test-önce iş akışı, hata ayıklama ve kod inceleme becerileri, inceleyici ajan. Şu an geliştirici modu (taslak, test, geri alma) ve onaylı program çalıştırma var.
- Codex ve OpenCode worker olarak bağlanacak, yalnız ücretsiz kipte: OpenCode varsayılan yerel Ollama modeliyle, isteğe bağlı ücretsiz modellerle veya ücretsiz Gemini / Groq anahtarıyla; Codex yalnız yerel kipte (`codex --oss`). Paralel kodlama için ayrı çalışma alanı gelecek. Şu an Jarvis'te yok. Claude Code Jarvis'in içinde kullanılmaz.
- CI takibi, issue iş akışı, bağımlılık incelemesi, depo bağlam dosyaları ve git diff bağlamı eklenecek; kod eylemi makbuzları tamamlanacak. Şu an PR açma ve yerel çalışma ağacı yayını var.

---

## Faz 7 — Alt-ajan ve Kanban

**Durum: başlanmadı.**

Alt-ajan yaşam döngüsü ve Kanban panosu eklenir. Sandbox hazır; paralel iş ancak güvenli ortamda dağıtılabilir.

- Alt-ajan yaşam döngüsü tamamlanacak: yalıtılmış bağlam, çalışanları listeleme, yönlendirme, durdurma, iptal, iş ve token bütçesi, eşzamanlılık ve derinlik sınırı. Şu an kalıcı görev grafı, paralel çalıştırma ve iptal var; yönlendirme ve derinlik sınırı yok.
- Yapılandırılmış alt-ajan çıktısı eklenecek: JSON şema sözleşmesi, bozuk çıktıda sınırlı düzeltme, kısmi / yarıda kalan / bütçesi biten / bilinmeyen sonucun ayrı gösterimi. Şu an tek tip sonuç var.
- Görev ve alt-ajan bazlı araç kısıtı ile devir sözleşmesi eklenecek. Şu an uzman tanımlarında kısıt var.
- Alt-ajan başına terminal, model ve profil yönlendirmesi ile takılabilir delegation arka ucu eklenecek; yalnız kendi makinelerinize. Sandbox'tan sonra.
- Kanban panosu eklenecek: görev oluşturma, sahiplenme, tamamlama, nedenli engelleme, insan engel kaldırma, bağımlılık, ana / alt görev, ek dosya. Şu an kuyruk, bağımlılık ve kalp atışı var, pano yok. Core Job'ın yerine geçmez, yalnız görünümdür.
- Kanban inceleme akışı eklenecek: inceleyici atama, değişiklik isteme, inceleme tamamlama, olay hook'ları, çok ajanlı iş dağıtımı.

---

## Faz 8 — MCP istemcisi ve güvenli eklenti

**Durum: 🟡 kısmi. Kamera/WebRTC cihaz bridge adapter'ı mevcut web Bridge yüzeyine bağlı; uzak kamera karesi artık mevcut Vision/`observe(camera)` analiz yoluna da bağlanıyor. Gerçek cihaz kabulü ve gerçek WebRTC signaling tamamlanmadan bu iş ✅ sayılmaz.**

MCP istemcisi ve güvenli eklenti sistemi eklenir. Kendi altyapımız sabit; dış araçlara ancak o zaman güvenle kapı açılır.

- 🟡 Kamera/WebRTC cihaz köprüsü: yalnız observation/evidence kaynağı; yerel stop uzaktan yeniden açılamaz, en fazla 3 viewer, WebRTC/JPEG frame sınırı, owner izolasyonu ve ephemeral retention var. Goal/Vision observation bağlantısı yapıldı; gerçek cihaz kabulü ve gerçek WebRTC signaling bekliyor.
- Sabit, salt okuma MCP istemcisi eklenecek: dinamik araç keşfi, sunucu bağlantıları, MCP olay istemcisi, yerel MCP bağlantıları. Sandbox'tan sonra. Şu an yalnız referans kataloğu var.
- A2A ve harici ajan servislerine bağlanma en sona kalır.
- Güvenli eklenti sistemi sıfırdan yazılacak: araç, yaşam döngüsü hook'ı, komut, paketlenmiş skill, katalog, katman, commit'e sabitli sürüm, onay, işletim sistemi uyumu. Şu an eski `plugins.py` kullanıcı Python'unu doğrudan yüklüyor; o büyütülmeyecek.
- Sağlayıcı eklentileri eklenecek: model, hafıza, context motoru, bilgisayar kontrolü, yerel TTS, yerel STT, delegation, gateway.
- Araç setleri eklenecek: birleşik, özel ve platforma özel setler, araç bazında aç / kapat, iş akışı kapılı araçlar, araç arama. Şu an merkezi araç kaydı ve izin politikası var.
- Bağlantı katmanı eklenecek: kendi bağlayıcılarımız, adlandırılmış hesaplar, hesap yeniden adlandırma, bağlayıcı onay ekranı, aynı uygulamada çoklu hesap, kimlik bilgisi yalıtımı. Şu an kullanıcıya özel belirteç ve servis yapılandırması var.

---

## Faz 9 — Bilgisayar kontrolü

**Durum: başlanmadı.**

Core tarafı bilgisayar kontrol sözleşmesini tamamlar; fare ve klavye tarafı C# PC Worker'ın işidir. Tüm temel altyapı hazır olmadan fiziksel kontrol eklenmez.

Onaylı bölünme: Jarvis-v2 yalnız Core tarafını yapar (yetenek manifesti, izin ve etki politikası, WorkerResult sınırı, makbuz, IPC sözleşmesi, salt okuma benchmark). Fare, klavye ve C# kısmı ayrı PC Worker'ın işidir (mimari belge §16).

**Core tarafı (Jarvis-v2):**

- IPC sözleşmesi kodlanacak: yalnız yerel ve aynı kullanıcı (ACL'li named pipe veya stdio, ağ portu yok), sürüm uzlaşması ve `CONTRACT_MISMATCH`, komut / iptal / iptal onayı. Şu an yalnız mimari belgede tanım var.
- Girdi modu ve lease eklenecek: `uia_pattern` (odak ve imleç çalmaz, pencere lease'i, kullanıcı aynı anda çalışabilir) ve `physical_input` (masaüstü geneli lease, kullanıcı girdisinde durur). Worker modu kendiliğinden yükseltmez. Şu an yok.
- PC capability'leri manifeste satır satır girecek (`pc.window.control`, `pc.input.click`, `pc.input.type` vb.), her birinin izin sınıfı, onay kuralı ve makbuz türüyle. Şu an tek `goal.desktop` satırı var.
- Hedef sınıfları Core politikasına yazılacak: Jarvis penceresi ve uzak erişim yasak; terminal, kod editörü, tarayıcı ve şifre yöneticisi açık ama her eylemde ayrı onay ve makbuz ister, şifre alanı okunmaz. Yönetici yetkili hedefte Worker kendini yükseltmez, ayrı capability ve her seferinde onay ister.
- Site ve köken bazlı izin listesi tarayıcı dışı akışlara yayılacak. Şu an tarayıcı alan adı kapısı var.
- Acil durdurma: tek komutla çalışan PC işini iptal etme ve lease'i bırakma. Şu an genel iptal var, PC'ye özel yok.

**PC Worker tarafı:**

- Gerçek Windows PC'de CUA arka ucu UIA temeline karşı ölçülecek; yetmezse C# Windows-native yedek gelecek. Arka planda, imleç ve odağı çalmadan çalışma, kaydırma ve sürükleme eklenecek. Şu an Hesap Makinesi ve Not Defteri pilotu var, genel girdi yok.
- Genel tıklama, yazma, kaydırma, sürükleme, klavye kısayolu, pencere ve uygulama hedefleme ve yönetici yetkili uygulamalar için ayrı güvenli yol eklenecek. Şu an kontrol çağrısı (Invoke / Value) var.
- Görüntü tabanlı yedek, ajan imleci, kullanıcı ve ajanın eşzamanlı çalışması ve her PC eyleminde makbuz eklenecek. Şu an sonuç geri okuma var, makbuz tam değil.
- Yerel Windows uygulama kontrolü Hesap Makinesi ve Not Defteri dışına PC Worker üzerinden çıkacak. Şu an uygulama izin listesi var.
- macOS ve Linux arka uç adayları değerlendirilecek (düşük öncelik).

---

## Faz 10 — Dışarıya etki eden işler

**Durum: başlanmadı.**

Telegram/WhatsApp, Gmail ve Takvim gibi dışarıya etkili yazma işlemleri eksiksiz tamamlanır. Salt okuma yolları hazır; yazma her adımda makbuz ve doğrulama ister.

Her yazma işlemi kesin hedef, niyet kaydı, makbuz ve okuyup doğrulama ister.

- Telegram ve WhatsApp için ortak mesajlaşma ağ geçidi eklenecek: adaptör arayüzü, eşleştirme, kimlik doğrulama, gelen oturum yönlendirme, sağlık izleme, güncelleme sonrası toparlanma. İkisi de telefondan yazmak için kalır; aynı tek Jarvis oturumudur. Şu an tek tek gönderim adaptörleri ve WhatsApp webhook'u var.
- Telegram gelen mesaj ve DM işlemleri tamamlanacak; platforma özel araç seti eklenecek. Şu an giden mesaj ve bot güncelleme alıcısı var.
- Gmail'e yanıt, taslak, arşivleme, çöpe atma ve etiketleme eklenecek; gönderim sonrası okuyup doğrulama ve teslim makbuzu tamamlanacak. Şu an gönderim var, okuma geniş.
- Takvime etkinlik oluşturma ve güncelleme, takvimden hatırlatma, mailden görev çıkarma ve mailden GoalState'e devir eklenecek. Şu an takvim yalnız okuma, mailden tarihli iş çıkarma var.
- Birden fazla Google hesabı ve iş / kişisel ayrımı için hesap soyutlaması eklenecek. Şu an kullanıcıya özel tek belirteç var, Outlook ayrı.

---

## Faz 11 — Profiller, hafıza, context

**Durum: 🔄 kısmi — #421 Physical Object Memory açık PR; CI/watcher kabulü bekleniyor. #454 Canonical Brain Contracts v1 contract foundation merge edildi; Canonical Active Context builder read-only snapshot foundation, Candidate Builder v1, Reference Resolver v1 ve Understanding Engine v1 merge edildi. #460 Exact State Gate + Deterministic Fast Gate merged foundation. #461 PR7 Text/Web/Audio/Phone production entry + Core handoff merge edildi; PR7 Closeout-A (continue_voice yapılandırılmış resume, history_limit üst sınırı, last_property, yazım düzeltme tek geçiş, gerçek BrainFeedback) #463 ile merge edildi. Closeout-B0 #464, B1 #465, B2 #466 merge edildi ancak kapsam dar kaldı (yalnız `pc.level.set` + `weather.*` Core'a geçti); capability_hint → Core'un kalanı, candidate/reference execution ve eski regex/resolver otoritesi B3a/B3b'dedir. Advisor + Echo + Failure Synthesis YOK; Live parity YOK; legacy retirement/final sweep YOK. Fazın geri kalan maddeleri başlanmadı.**

Kullanıcı profilleri, uzun dönem hafıza, context sıkıştırma ve kendini geliştirme eklenir. Tüm yetenekler çalışıyor; kişisel uyarlama ve büyüme bunların üstüne oturur.

- 🔄 (#421) `[1✓ 2– 3✓ 4–]` Physical Object Memory: kamera/Vision gözlemi `Observation -> CandidateFact -> kullanıcı onayı -> durable object memory` hattından geçer. Aday kayıtlar relevance prompt'a girmez; onaylı kayıt mevcut `facts` + relevance gate hattına bağlanır. Provenance tutulur, manuel düzeltme sonraki model taramasıyla ezilmez, bir taramada görülmeyen nesne silinmez (`location_unknown`), nesne/QR/etiket metni untrusted evidence olarak kalır. Güncel head için CI + gerçek PC watcher PASS gelmeden tamamlandı sayılmayacak.
- 🟡 (#454) `[1✓ 2✗ 3✗ 4✗]` Canonical Brain Contracts v1 eklendi: `ActiveContext`, `UnderstandingResult` ve `BrainFeedback` Brain migration'ın sözleşme temelidir. Active Context, Candidate Builder, Reference Resolver ve Understanding Engine v1 foundationları merge edilmiştir; Exact State Gate + Deterministic Fast Gate #460 ile merged foundation'dır. #461 production Text/Web/Audio/Phone entry + Core handoff merge edilmiştir; Closeout-A (#463) merge edildi; Closeout-B yalnız kısmen (level + weather) yapıldı, kalanı B3a/B3b'dedir. Advisor + Echo + Failure Synthesis, Live parity ve legacy retirement/final sweep YOK; `WorkerResult v1` değişmedi.
- 🟡 (`brain-active-context-v1`) `[1✓ 2✗ 3✗ 4✗]` Canonical Active Context builder mevcut SessionStore, bounded/reset-aware history, açık GoalState ve dar Profile/Hoca state'lerinden yalnız read-only `ActiveContext` snapshot üretir. İkinci truth source veya durable Brain store YOK; Candidate Builder, Reference Resolver, Understanding Engine v1 ve #460 Exact/Fast Gate foundationları merge edilmiştir. #461 production entry + Core handoff merge edildi; B3b'ye kadar eski context/aday yolları duruyor. Live parity ve legacy retirement/final sweep YOK.
- 🟡 (`brain-candidate-builder-v1`) `[1✓ 2✗ 3✗ 4✗]` Canonical Candidate Builder v1 foundation merge edildi: gerçek stable-ID taşıyan Profile task/note/event kayıtları, mevcut canonical `ActiveContext` referansları ve read-only global dosya envanterinden bounded `ContextReference` candidate setleri üretir. Stable ID taşımayan Profile goals/facts/rules targetable candidate yapılmaz. Candidate Builder kendi başına target/reference resolution, permission/effect authority veya model çağrısı yapmaz. #461 production entry içinde kullanımı merge edildi; eski aday üretimi B3b'de silinecek.
- 🟡 (`brain-reference-resolver-v1`) `[1✓ 2✗ 3✗ 4✗]` Canonical Reference Resolver v1 foundation merge edildi: yalnız verilen mevcut `ContextReference` candidate seti üzerinde deterministic/bounded explicit identity, exact name/title/text/label, file path/name/stem ve bounded deictic reference proposal üretir. Candidate/source discovery, TTL/lifecycle ownership, permission/effect authority ve model çağrısı YOK. Understanding Engine v1 ve #460 Exact/Fast Gate foundationları merge edilmiştir. #461 production entry içinde resolver kullanımı merge edildi; legacy resolver (chat_translation._sources/resolve, _resolve_doc) retirement B3b'de (non-Live caller'lar) ve PR9'da (Live), final sweep YOK.
- 🟡 (`brain-understanding-v1`) `[1✓ 2✗ 3✗ 4✗]` Canonical Understanding Engine v1 foundation merge edildi: mevcut `ActiveContext` + candidates + resolved references + current user text üzerinden yalnız `UnderstandingResult` proposal üretir. `request_kind`, `conversation_relation`, `temporal_need`, advisory `capability_hint`, semantic arguments, canonical context actions, confidence/ambiguity/assumption/reason-code alanları bounded deterministic kurallarla önerilir. Permission/effect/execution/completion authority YOK; provider/model bağımlılığı YOK; source read veya durable state mutation YOK. #461 production entry + Core handoff merge edildi; B3b'ye kadar eski context/aday yolları duruyor. Advisor + Echo + Failure Synthesis ve legacy retirement/final sweep YOK.
- 🟡 (#460 / `brain-exact-fast-gates-v1`) `[1✓ 2✗ 3✗ 4✗]` Canonical Exact State Gate + Deterministic Fast Gate merged foundation'dır: yalnız mevcut bounded state/protocol ile exact kullanıcı cevabı eşleştiğinde veya context-independent exact fast komut bulunduğunda non-authoritative `GateObservation` üretir. `state exists ≠ next utterance belongs to that state` invariantı korunur; open-ended pending cevapları PR5 Understanding alanında kalır. Permission/effect/completion authority, model/router/resolver çağrısı YOK. #461 production Brain/Core entry wiring'i merge edildi; eski yorum yollarının silinmesi B3b/PR9'dadır.
- 🟡 (#461 + Closeout-A / `brain-production-entry-v1`) `[1✓ 2🔄 3🔄 4✗]` Text/Web/Audio/Phone request girişleri mevcut owner-bound RID ile canonical `ActiveContext → Exact State Gate → Deterministic Fast Gate → Candidate Builder → Reference Resolver → Understanding` sırasına ve mevcut Core/domain handoff'una bağlanıyor. Brain yalnız proposal/observation üretir; permission/effect/worker/completion authority Core'da kalır. #461 (555ad2f) ve Closeout-A/B0/B1/B2 (#463–#466) merge edilmiştir. Advisor + Echo + Failure Synthesis YOK; Live parity YOK; legacy retirement/final sweep YOK.
- 🔄 (PR7 Closeout-A) `[1✓ 2🔄 3✓ 4✗]` #461 sonrası kapanış: `app_actions.continue_voice` artık `router.classify` çağırmıyor (yalnız sunulan seçeneklerden birini seçen yapılandırılmış resume; serbest cevap yeni istek olarak Brain girişine döner); `build_active_context` `history_limit` üst sınırı 50; `last_property` (volume/brightness, owner bazlı, 10 dk) ActiveContext'e görünür ve çıplak "70 yap" yalnız taze last_property varsa doğrudan uygular, yoksa/bayatsa/geçersizse sormaya devam eder; yazım düzeltme `runtime.handle` özyinelemesi yerine `handle_request` içinde tek açık yeniden geçiş; `BrainFeedback` Core sonucundan (handled/needs_input/failed/cancelled) üretilir; ölü `canonical_fallback` silindi; hedef durumu kuyruk kısayolu kaldırılmadı (komut döngüsü doluyken yanıt vermesi ürün invariantı) ama tanıma tek kanonik `brain_gates.goal_status_selection` üzerinden. Closeout-B'nin kalanı B3a/B3b satırlarındadır.
- 🔄 (PR7 Closeout-B1) `[1✓ 2🔄 3✓ 4✗]` Core tarafında `brain_core_map` allowlist'i: Brain `capability_hint` + argümanları yalnız burada listelenen ve Core'un yeniden doğruladığı intent'e (`pc.level.set` → `level_set`) dönüşür, ham metin eski handler'a tekrar yorumlatılmaz. Understanding çıplak/açık seviye isteğini (`sesi 50 yap`, `70 yap`) çözer: taze `last_property` varsa uygular, yoksa `LEVEL_UNSPECIFIED` ile sorar ve Core `pending_level` açar. `hedef durumu` kuyruk kısayolu artık kendi ifade listesi tutmaz: `brain_entry.fast_lane` (yalnız deterministik Fast Gate, boş context) queue-safe protokolü (`fast.goal.status`) tanır. Acceptance: 443 senaryo, 0 regression/changed, 11 better (k-70-*, k-ses-50, k-parlaklik-30, k-yuzde70-volume, 2 yönlendirme cümlesi). **YAPILMADI:** `router.classify` silinmedi, çünkü Brain'e girmeyen tek üretim çağıranı Live `_live_command`'dır (PR9); Brain'den girilen hiçbir istek classifier'a ulaşmıyor (AST denetimi testte kilitli). `work_modes` de duruyor: router'ın yanında `goal_executor` da `work_modes.ends_with_action`'ı üretimde çağırıyor (B3b'de Brain kararına taşındı, Live yedeği PR9'da silinecek). `freshness`'ı yalnız router import ediyor; router silinince birlikte gider. Diğer capability hint'leri: weather B2'de Core'a alındı; files, notes, reminder, research Core'a bağlanmadı (B3b'de legacy sahibi adlandırıldı, Core intent'i B3c); regex ön kapıları B3a'da precedence sözleşmesine bağlandı, silinmeleri PR9.
- 🔄 (PR7 Closeout-B2) `[1✓ 2🔄 3✓ 4✗]` Hava durumu Core allowlist'ine alındı (`weather.read`/`weather.read.current` → `weather`): şehir Understanding'de çıkarılır (eski `_city_in` mantığı, aynı stop-word kümesi), Core doğrular ve büyük harfe çevirir. Açık `pending_level` varken açık bir seviye isteği (`sesi 30 yap`) artık eski soruyu geçersiz kılar: Core planı çalışır, `level_set` bekleyen soruyu temizler, eski handler pending'deki eski değeri uygulamaz. Diğer açık pending durumları planı engellemeye devam eder. Uçtan uca test: gerçek `SessionStore` → `build_active_context` → `prepare` → `handoff`. Acceptance: 443 senaryo, 0 regression; 2 bilinçli `changed` (`k-cap-01`, `rota-20ef3a970a`: aynı outcome, handoff yolu eski handler → Core dispatch) `tests/data/brain_acceptance_kabul_gecmisi.json` ile gerekçeli kabul edildi. **YAPILMADI:** uygulama aç/kapat, notes, files, reminder, research hint'leri, `engine_commands`/`_extra_commands`/`command_manager` regex ön kapıları ve `goal_executor` içindeki `work_modes.ends_with_action` çağrısı. Sebep: bu ön kapıların silinmesi Live (`_live_command`) bağlanana kadar (PR9) mümkün değil; hint'i Core'a bağlamak ise `windows_settings`/`selfctl`/`_file_command` gibi önceki kapıları atlayıp yanlış hedefe işlem riski taşıyor.
- 🔄 (PR7 Closeout-B3a) `[1✓ 2🔄 3✓ 4✗]` Doğruluk/güvenlik kapanışı: (1) seçenekli clarify cevabı (`2`, `Plan – Chrome`) `prepare→handoff→continue_voice` ucundan geçer: Exact State Gate yeni `session.pending_action.clarify_select` protokolüyle yalnız sunulan seçeneklerden birini tanır (tek tanım `confirmation.choice_index`), süresi dolmuş clarify tüketilmez; seçenek eşleşmeyen cevap yeni istektir ve açık clarify'ı geçersiz kılar (eskiden handler atlanıp chat'e düşüyordu, `pending_action` kalıyordu). Onay tipi `pending_action` eskisi gibi engelleyicidir. (2) Fotoğraf yolu gerçek `BrainFeedback` üretir: soru bekleyen foto `needs_input`, exception `failed`, iptal `cancelled`. (3) Legacy front-gate precedence sözleşmesi `modules/brain_precedence.py`: `windows_settings → selfctl → _user_command → _planner_command → macro_teach/manage/run → _extra_commands` sırası Core weather/level planından ÖNCE değerlendirilir; kapı cevap verirse Core çalışmaz; sıra `engine_commands.handle` ile test altında kilitli. Acceptance: 443 senaryo, 0 regression, 1 bilinçli `changed` (`k-clarify-cevap`, `tests/data/brain_acceptance_kabul_gecmisi.json`). Bilinen, değişmeyen sınır: "ses 40 yap ve hava nasıl" gibi çok niyetli cümle yalnız ilk eşleşeni çalıştırır (legacy ile aynı). **YAPILMADI (B3b):** files/notes/reminder/research Core mapping, `semantic.references` execution hedefi, `_resolve_doc`/`reference_context`/`chat_translation` non-Live caller'ları, `goal_executor` `work_modes`.- 🔄 (PR7 Closeout-B3b) `[1✓ 2🔄 3🔄 4✗]` Doğrulanan kapanış: `goal_executor` soru bekleyen hedefe gelen cümlenin cevap mı yeni istek mi olduğunu Brain kararından (`brain_entry.goal_question_superseded`: CAPABILITY / CONTEXT_CONTROL / TOPIC_CHANGE veya Understanding'in `ENDS_WITH_ACTION` reason code'u = yeni istek) alır; eylem-fiil kuralı tek tanım olarak `modules/brain_actions.py`'de (Brain sahibi), `work_modes` onu import eden Live-only katman (PR9'da silinir). 40 cümlelik eski/yeni tablo: 0 gerileme, 4 bilinçli iyileşme (yarın hava nasıl olacak, bana hatırlat, belgeyi özetle, ankara'da hava nasıl); 17 hedef-sorusu senaryosu 443 kapısında (460 senaryo). İç içe adım (`önce X sonra Y`, macro) tüm cümlenin entry'sini taşıdığı için eski kurala döner. `brain_core_map.LEGACY_OWNED_HINTS`: Core'a bağlanmayan her hint (`notes.read`, `files.read`, `reminder.propose`, `research.search`) adı konmuş bir legacy sahibine bağlıdır ve sahipsiz hint testte hata verir; hint'ler bilerek Core'a bağlanmadı çünkü Understanding bu yetenekler için doğrulanabilir argüman (hedef dosya, zaman, sorgu) üretmiyor — ham metin yeniden yorumlanmaya devam ediyor ve bu açık borçtur. Brain akışı doküman intent'i (`doc_*`) üretemez; `_resolve_doc`, `reference_context`, `router.classify` için caller-zero kapıları testle kilitli (yeni çağıran test kırar). **YAPILMADI:** semantic.references'ın dosya işlemlerinde execution hedefi olması, `chat_translation.resolve/_sources` (Live ile paylaşılan `command_manager` zincirinde), `brain_context` varsayılan `chat_translation.recent` bağımlılığı, files/notes/reminder/research için Core intent'leri. Bunlar yeni Core yeteneği ister; PR9 caller-zero listesi migration map'te.
- 🔄 (PR7 Closeout-B3c-1) `[1✓ 2🔄 3✓ 4✗]` `files.read` kısmen Core'a bağlandı: Understanding yalnız TEK çözülmüş `file` referansı (Candidate Builder envanteri → Reference Resolver) ve `özetle` fiili varsa `operation=summarize` + `path` önerir; yol ham metinden asla gelmez. `brain_core_map._file_args` Core'da yeniden doğrular (mutlak yol, mevcut dosya, `nxapi.allowed`) ve mevcut `doc_summary` intent'ine verir; `_resolve_doc` bu yolu aynen alır, yeniden hedef seçmez. `_file_command` (dosya düğmesi komutları) `brain_precedence.FRONT_GATES` başına eklendi, Core planından önce çalışır. Dosya uzantı tanıma genişletildi (txt/md/csv/xls(x)/ppt(x), `dosyasını`). Uçtan uca `prepare→handoff` testleri; acceptance 460 senaryo 0 regression. Eksik/çoklu aday: Core netleştirir (`FILE_TARGET_UNRESOLVED`), legacy `_resolve_doc` tahmini yok. Core'un reddettiği (`nxapi.allowed` dışı, symlink kaçışı, yok) dosya için dürüst "erişemiyorum" cevabı ve `BrainFeedback failed/FILE_TARGET_NOT_ACCESSIBLE`. "özetle ve çevir" gibi çok işlemli cümle tek özet olarak planlanmaz, tamamı legacy sahibine kalır (adım Core'da sessizce düşmez). Acceptance bilinçli changed: `enj-TR-INJ-08` (`tests/data/brain_acceptance_kabul_gecmisi.json`). **YAPILMADI:** göster/aç/bul/listele/karşılaştır, çevir, dönüştür, analiz operasyonları (`PARTIAL_CORE_HINTS`), `chat_translation.resolve/_sources` (çeviri Core intent'i gelene kadar zincirde), notes/reminder/research (B3c-2..4).
- 🔄 (PR7 Closeout-B kabul kapısı) Kabul dosyaları tek kanonik baseline'da birleştirildi: `tests/data/brain_acceptance_baseline.json` (460 senaryo) yeniden alındı, B2/B3a/B3c-1 `--accept` dosyaları kaldırıldı, gerekçeleri `tests/data/brain_acceptance_kabul_gecmisi.json` denetim kaydında. Argümansız `python scripts/brain_acceptance.py compare` GEÇTİ der ve bu `test_default_compare_passes_without_arguments` ile kilitli; bundan sonraki bilinçli değişiklik yeni baseline + gerekçe satırı ister.

### Ek kabul kriterleri — Fable/Claude agent benchmark

- **Tespit edildi — uygulama bekliyor: öğrenilmiş kurallar Core ve izin politikasını geçersiz kılamaz.**
  - **Kod kanıtı:** İlk uygulama PR'ı learned-rule/memory uygulama noktasında açık precedence kontrolü göstermeli; öğrenilmiş kural yalnız advisory/context girdisi olabilir ve Domain invariant → Decision Authority → JIT Permission → Effect Policy sırasının sonucunu değiştirememelidir.
  - **Beklenen davranış:** Daha önce öğrenilmiş bir tercih veya kural "bunu otomatik yap", "bu alıcıyı kullan" ya da "onay isteme" dese bile Core hedefi, izin sınıfını veya kullanıcı onayı gereksinimini değiştiremez.
  - **Kabul testi:** Öğrenilmiş kuralın hedef/alıcıyı değiştirmeye veya gerekli onayı atlamaya çalıştığı senaryoda execution kararı değişmeden kalmalı ve işlem mevcut Core/Permission politikası uyarınca reddedilmeli ya da onay istemelidir.
- **Tespit edildi — uygulama bekliyor: ilgisiz hafızayı bağlama almama (memory relevance gate).**
  - **Kod kanıtı:** Uygulama PR'ında hafıza adaylarının bağlama girmeden önce görevle ilgililik filtresinden geçtiği ve filtre sonucunun testle kilitlendiği gösterilecek.
  - **Beklenen davranış:** Hafıza yalnız mevcut sorunun sonucunu, önerisini veya gerekli bağlamını gerçekten değiştiriyorsa kullanılacak; alakasız geçmiş ayrıntılar yalnız "hatırlıyorum" göstermek için prompt/context'e eklenmeyecek.
  - **Kabul testi:** Aynı kullanıcı için biri görevle ilgili, biri ilgisiz iki hafıza verildiğinde yalnız ilgili olanın oluşturulan bağlama girdiği; ilgisiz olanın model girdisine taşınmadığı kanıtlanacak.

- Kullanıcı profilleri eklenecek. Jarvis tek örnek, tek oturum, tek arayüz kalır. Asıl kullanıcı Hamdi. Biri "ben Hasan" derse (sesle ya da yazarak) Jarvis Hasan'a göre çalışır; Hasan'ın kendi ayrı hafızası ve geçmişi olur. Kısıtlama yoktur, her profil her özelliği kullanır. Geliştirici menüsü şifresi olduğu gibi kalır. Şu an owner alanı ve kullanıcıya özel belirteç var, sözle profil geçişi yok.
- Oturum arama, çapraz oturum hatırlama, oturum üst-alt ilişkisi, oturum meta verisi, geçmiş arama ve hafıza ön yükleme eklenecek. Şu an kalıcı sohbet geçmişi var, arama yok.
- Hafıza sağlayıcı arayüzü eklenecek, yalnız kendi sunucunuzdaki Mem0 ve Honcho ile; hafıza yaşam döngüsü hook'ları gelecek ve hafızaya yazmadan önce gizli bilgi temizliği yazım yoluna bağlanacak. Şu an yerel profil ve kural hafızası var, maskeleme yazım yoluna bağlı değil.
- Proje ve ortam hafızası Hoca dışına yayılacak; konuşma hafızası ile GoalState ayrımı koda yazılacak. Şu an Hoca oturum hafızası var.
- Kendini geliştirme dilimi eklenecek: iz yakalama, iyileştirme adayı, tekrar üreten test, taslak PR, skill ve prompt evrimi. İnsan onaylı, kendi kendine merge yok, geliştirici menüsünde. Şu an kural öğrenme ve onay bekleyen öneri var.
- Context sıkıştırma eklenecek: token farkında, bekleme süreli, başarısızlıkta yedek yol, taşma toparlama, karar ve yapıt koruma. Şu an hiç yok.
- `@dosya`, `@klasör`, `@git-diff` ve `@URL` bağlam referansları ile bağlam dosyaları eklenecek. Şu an yok.

---

## Faz 12 — Düşük öncelikli alanlar

**Durum: başlanmadı.**

Medya düzenleme, ses sağlayıcısı, yedekleme, akıllı ev ve toplu işleme gibi istenen ama acil olmayan alanlar tamamlanır. Temel sağlamsa buraya gelir.

- Yerel çalışan medya becerileri eklenecek: görsel düzenleme, video analizi, HTML'den video, ComfyUI, Manim, ASCII video, p5.js, web tasarım, şarkı sözü, metin insansılaştırma. Şu an görsel üretim, sahne montajı ve FFmpeg video var.
- Ses ve görsel sağlayıcı soyutlaması eklenecek: yerel Piper, Kokoro, XTTS, whisper.cpp ve yerel komut tabanlı TTS / ASR. Şu an edge-tts, Piper / SAPI ve faster-whisper doğrudan bağlı.
- Yönetim ekranları tamamlanacak: ağ geçidi, skill, eklenti, bağlantılar, günlükler, sağlık, kullanım, oturum ve zamanlama ekranı, masaüstü proje bağlamı, kenar çubuğuna sabitleme. Şu an ana, sohbet, dosya, görüntü, harita, uygulama ve ayarlar sayfaları var.
- Yedekleme ve taşıma eklenecek: ayar, hafıza, skill, oturum, profil ve tam yedek; kimlik bilgisiz tek profil dışa aktarma; PC'den PC'ye taşıma; başka ajan sisteminden içe aktarma (OpenClaw dahil). Şu an yalnız güncelleme öncesi yerel yedek var.
- Kararlı sürüm kanalı, sürüm sabitleme ve bağımlılık sağlığı tamamlanacak; bozuk kurulum kurtarma, çalışma klasörü eksik tespiti ve kurulum / taşıma sihirbazı eklenecek. Şu an güvenli güncelleme, geri alma ve bağımlılık kilidi var.
- Home Assistant, akıllı ev ve IoT, Spotify dışı müzik denetimi ve yazıcı dışındaki cihaz kontrolü eklenecek. Şu an yazıcı (OctoPrint / Moonraker), Spotify ve onaylı cihaz kaydı var.
- Toplu işleme (binlerce girdi) ve kendi makinenizdeki uzak worker eklenecek; eksik yetenekte kullanıcıya açıklama ve kurma onayı ile. Şu an tek makine kuyruğu ve yetenek keşfi var.

---

## Listede olmayanlar

**Ücretli veya kart isteyen:** Brave, Perplexity, Parallel, xAI, X (Twitter) ve X API, Modal, Daytona, Mem0 / Honcho / Supermemory bulut sürümleri, bulut worker, Alpha Vantage, prompt önbellekleme ve araç ağ geçidi, bulut video ve görsel üretimi, ses klonlama hizmetleri, yapay zekâ sunucu avatarı, ücretli şifre yöneticileri ve ücretli yönetilen bağlayıcı hizmetleri.

**Karar gereği çıkarılanlar:** anahtar havuzu, Jarvis'i MCP veya API sunucusu yapmak, IDE istemcisi, ses tanıma, uzak PC ve çoklu oturum, çoklu arayüz.

**İstenmeyen alanlar:** Notion, Obsidian, Box, Airtable; algılanmayan tarayıcılar (Camofox gibi); uzman grup sohbeti ve `@bahsetme`; Telegram ve WhatsApp dışındaki mesajlaşma platformları; worker / eklenti pazarı.

---

## Ortak kurallar

- **"Bitti" kuralı:** Bir faz ya da madde ancak dört koşulun hepsi sağlanınca bitmiş sayılır: (1) sözleşme / arayüz yazıldı, (2) eski kod göçü tamamlandı, (3) yeni kod kullanıcı akışına bağlandı, (4) eski kod / legacy kısım kaldırıldı. Her PR açıklaması hangi koşulları kapattığını yazar; durum güncellemesi bu dört koşula göre yapılır, PR sayısına göre değil.
- **UI/Core authority sınırı:** UI presentation/interaction katmanıdır; business/decision/execution authority canonical backend/Core'da kalır. UI kullanıcı girdisini iletir ve canonical state/evidence/result bilgisini gösterir. Presentation-only özellikler dışında UI tamamen silinse backend/Core davranışı ve canonical sonuç yaşamaya devam etmelidir. `modules.architecture_guard` yeni UI→Core authority dependency edge'lerini blocker yapar; #441/#444 sonrası güncel UI authority baseline boştur ve eski borcun geri eklenmesi `ARCH-006` blocker'dır. Ayrıntı: `docs/architecture/JARVIS_UI_CORE_BOUNDARY.md`.
- Her faz ayrı dalda, küçük PR'larla ilerler; AGENTS.md'ye göre önce plan ve iki seçenek, sonra sizin onayınız.
- Dış kod alınmadan önce lisans, Windows uyumu, güvenlik ve Core sözleşmesi kontrol edilir.
- Hiçbir yetenek ikinci bir Core kurmaz.
- Ajan çalışma akışı: ajan yalnızca PR açar → PR Hamdi'nin bilgisayarında açık kalır ve test edilir → Hamdi "kontrol et" deyene kadar ajan bekler → onaylanırsa ajan merge eder → bir sonraki işe geçmeden önce Hamdi'ye sorar.

---

## Referans noktaları

- **hermes-agent** (MIT) — 705 maddelik hasat listesinin çıktığı kaynak. Doğrudan alınabilecekler: `skills/` talimat dosyaları, `todo_tool.py`, `memory_tool.py`, `session_search_tool.py`. Bağlantı: https://github.com/nousresearch/hermes-agent

### Haber yayın zamanı / olay geçerlilik zamanı — kabul bekliyor

- Son dakika varsayılanı son 1 saat; açık saat aralığı önceliklidir. Bugün/bu sabah İstanbul zamanına göre değerlendirilir. Saatlik aralık doğrulanmış yayın saati ister; tarih-only kanıt saat uydurmaz.
- Yarın gibi olay tarihi, özgün isteğin zamanı ve açık kapsamına bağlıdır. Yayın tarihi kararın geçerlilik tarihi değildir. Kayıtlı olay kanıtı yeniden doğrulanır; eksik yer/kapsam mevcut Core soru akışına gider. Yerel resmî kaynak eşlemesi sınırlıdır; bütün kurumlar için yetki çözümü iddia edilmez.
- Yeni kod için Windows CI ve gerçek PC kabulü beklenir; Faz 4A veya genel web araştırması bu kayıtla tamamlanmış sayılmaz.

- Haber kabul tanısı: son-rapor dosyası başka PR ile değişebilir. Watcher reports/<exact-sha>.json arşivini silmeden korur; arşiv yazılamazsa worktree silinmez. --news kabulü eski watcher altında da LOCALAPPDATA/Jarvis/pc-acceptance/news-reports içine yalnız redakte haber kontrollerini zaman damgası ve kod parmak iziyle yazar. Kod parmak izi commit SHA kanıtı değildir. PR tanısı 300 karakterde kesilmez; başarısız dış keşif kontrolü de gösterilir. Bu kayıt iyileştirmesi Türkiye AI canlı arızasını çözülmüş saymaz; yeni exact kabul beklenir.

- Hoca ortak araştırma bağlantısı: ilk kaynak fail-fast davranışı için sınırlı aday geçişi hazırlandı. Ek model/fallback sağlayıcı yok. #443 haber zaman çalışmasından ayrı tutulur; gerçek dış arama/Hoca/PC E2E kabulü henüz tamamlanmış sayılmaz.

- #434 eski dalı güncel main ile normal merge için hazırlandı; haber/Hoca/Core düzeltmeleri korunur. Backend :latest alias regresyonu ve yanlış stale uyarısı düzeltildi. Yeni exact-head CI, UI ve gerçek Ollama inference kabulü olmadan kapanmış sayılmaz.

- #434 kabul helper yaşam döngüsü: web.serve sunucuyu zaten başlatır; local_model_acceptance ikinci serve_forever thread başlatmaz. Windows #901 exact e29d85cd UI ve gerçek inference PASS kanıtı verdi, fakat ikinci loop kapatılırken WinError 10038 görüldü. Önce thread-sahipliği regresyonu kırmızıyla doğrulandı; tek sunucu loop ve bir kez shutdown/server_close korunarak düzeltildi. Yeni exact head kabulü beklenir.

- #434 canlı kabul gerçek kurulu modelle yapılır; qwen2.5-coder:7b kurulumu şart değildir. 3B ve diğer model kimlikleri için aynı kurulu/effective/UI/inference şartları uygulanır. Senaryo (stale/normal/tercihsiz) açık raporlanır; yeni exact-head kabulü beklenir.

- #434 main uyumu: Faz 0 kapanış belgeleri ve ARCH-007 guard güncel main 4280ac9a ile korunur. Önceki 970c643c Windows CI #914, gerçek 3B UI/inference ve watcher PASS kanıtları yeni birleşmiş head kabulü yerine geçmez.

- 🔄 Faz 1 provider/Hoca tanısı: Ollama taşıyıcı timeout ve bağlantı yokluğu ayrı gösterilir; Hoca exhausted güvenli neden/metadata zincirini korur. Bu yalnız tanı düzeltmesidir; gerçek PC Hoca başarısızlık nedeni ve final provider/429/restart kabulleri açık kalır.

- Router durum tablosu kayıtlı model yerine mevcut backend effective çözümünü gösterir; model yoksa doğrulanamadı yazar. Son çağrı özeti tablodan önce gelir; RAM kaydı yoksa süreç/kullanıcı kaydı yokluğu açıkça belirtilir. Bu düzenleme restart dayanıklı health/last-call depolaması eklemez.

- 🔄 Hoca araştırma hata sınırı: kaynak keşif hatası yanlışlıkla genel planlayıcıya geçip ek model beklemesi yaratmaz. Aynı araştırma okuyucusu ve bütçesi korunur; arama hatası güvenli bildirilir, izin/iptal yutulmaz. Gerçek PC Hoca ve model performans kabulü henüz kapanmamıştır.
