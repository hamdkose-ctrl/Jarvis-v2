# Görev çekirdeği, hedef yürütücüsü ve araçlar (AGENTS.md alan notları)
- `external_write`, kullanıcının özel dış hesabındaki kesin kaydı oluşturma/değiştirme/silme sınıfıdır; varsayılanı her zaman `ask`tır ve süreli grant ile açılamaz. Açık `action_class` dış silmede `local_destructive`e çevrilmez; yıkıcılık capability Effect Policy'sinde taşınır. Para/kimlik, sistem ve fiziksel güvenlik sınıfları önceliğini korur.
- Sohbet haber teslimi yanlış writer seçimini yürütmeden mevcut bağımlı haber makbuzlarına çevirir. Kısmi teslim için chat_evidence yalnız görünüm referansıdır; hedefin tamamlanma kanıtı değildir. Kaynak eksikse hedef açık kalır; diğer hedefler ve gerçek dosya üretimi korunur.
- Araştırma son görünümünde aynı kanıt kimliği bir kez basılır. Aynı hedefte başarılı research varsa data sources/headlines/news_search keşif dökümleri son bulgulara karıştırılmaz; yalnız keşif hedefi, başka veri sonuçları ve dosya yolları korunur. Genel araştırmada kısa yanıt sonrası kaynak URL'si kesilmeden gösterilir. Kayıt/kanıt/planlama ve tamamlanma kuralları değişmez.
- `public_sources.address` veri taşıyan `data/payload/report/body/content/text/message` sorgu anahtarlarını tam adla reddeder; mevcut kimlik bilgisi filtresi ve meşru `date/city` sorguları korunur.
- `tests/test_public_sources_exfil.py` ağ öncesi ret ve yönlendirmeyi sınar; TR-INJ-16 artık bilinen açık değildir (anahtar kara listesi tüm veri sızdırma biçimlerini kapsamaz).

Bu dosya AGENTS.md'den taşındı; bölümler olduğu gibi, sırası korunarak buradadır. Tarihli bölümler geçmiş kararı anlatır; bir bölüm başka bir bölümle çelişirse tarihi daha yeni ve "son karar" yazan geçerlidir. Kod değişince ilgili bölüm burada güncellenir.

## GoalState cutover preflight — son karar (24 Ekim 2026)

Canonical GoalState hedef mimaride global lifecycle authority olacaktır; fakat mevcut runtime boyunca legacy `goal_executor` JSON journal write authority olarak kalır. Mevcut `goal_state_compat` projection/sync ve `goal_state_save_hook` compatibility katmanıdır, authority cutover değildir. Big-bang migration ve dual-write authority yapılmaz.

İlk gerçek cutover'dan önce identity (`owner`, `job_id`, `goal`, `execution_mode`), `done/cancelled` terminal sınırı, missing/corrupt canonical ve missing legacy davranışı, mevcut legacy → canonical state projection tablosu ile rollback/reconcile koşulları açıkça tanımlanıp testlenmelidir. Legacy journal'daki step/output/waiting/retry gibi yürütme bağlamı GoalState'e doldurulmaz; ileride ayrı ExecutionRecord sınırında taşınır. Ayrıntılı preflight sözleşmesi: `docs/architecture/GOALSTATE_CUTOVER_V1.md`.

Bu karar `goal_executor`, reducer/CAS, worker/effect/permission, planner veya subscription davranışını bu PR'da değiştirmez.

## Tamamlanma kararı saf policy'ye bağlandı (24 Ekim 2026)

`modules/completion_policy.py` yeni, bağımsız ve saf bir modüldür: sağlayıcı/ağ çağrısı yapmaz, dosya okumaz, hiçbir şeyi değiştirmez. `evaluate_evidence(check,*args,**kwargs)` var olan bir kanıt kontrolünü (örn. `_check_news_completion`/`news_policy.check_completion`) çalıştırır; kontrol normal dönerse `complete`, `ValueError` fırlatırsa `continue` (ve hatanın metnini `reason` olarak) döner, başka istisna türünü yutmaz. `job_decision(job)` ise `job['state']`'i salt okunur okuyup `done→complete`, `cancelled→terminal`, `question`/`approval→waiting`, diğerleri `continue` olarak sınıflandırır; yeni durum icat etmez.
`goal_executor.py`'deki `_check_news_completion` etrafındaki beş tekrarlı try/except ValueError bloğu (`_finish_completed`, `_loop_steps`'in goal yeniden-doğrulaması, `complete` aksiyonu, `_run`'ın resume-done kontrolü, `render`'ın kısmi gösterimi) artık `completion_policy.evaluate_evidence` üzerinden geçer; davranış aynıdır, karar artık ayrı ve test edilebilir bir yerdedir. `run()`'daki başarı-rotası tutma kontrolü de `completion_policy.job_decision` kullanır.
İlk gerçek örnek tek seferlik read-only haber/araştırma kanıtıdır (`news_policy.check_completion`); RSS subscription, cron, yeni planner veya GoalState cutover eklenmedi. Test: `tests/test_completion_policy.py` (saf fonksiyonlar, goal_executor importu gerekmez) ve mevcut `tests/test_goal_executor.py` regresyonsuz geçer.

## Kalıcı yürütmede toparlanma ve uzman seçimi — 17 Ekim 2026
- Son kontrol: 1378 Python testi OK (1 Windows DPAPI atlaması), 25 Node grubu ve 6 smoke grubu başarılı; 11 yeni varyasyon testi geçti. Son salt okunur kural incelemesi geçti. Windows canlı kabulü bu sonuçlara dahil değildir.
- Geniş Türkiye AI haber görevinde ilk, kaynak adımı başlamadan yapılan kısmi kurtarma iki yayıncıda durabilir; sonraki devam mevcut raporu koruyarak kalan kayıtlı dizinleri önce dener. Normal kaynak denemesi olan görevde de bütün dizinler önce denenir. İlk tekil aday başarısızsa aynı dizindeki ikinci gerçek bağlantı kalan bütçede denenir. 10 toplam kurtarma / 24 tur / 96 görev adımı ve 45 saniyeden sonra yeni ağ adımı başlatmama sınırları korunur; katalog taraması Türkiye'nin bütün haberlerini kapsadığı iddiası değildir.
- Kaynak denendi sayımı yalnız tam kayıtlı dizin URL'sinde started=true ve eşleşen done/failed sonuçla yapılır. Kuyruk, bellek bayrağı veya aynı alan adındaki başka yol yeterli değildir. broad_research salt kapsam sınıflandırmasıdır; tamamlanma kapısı açıkça o anki job kaydıyla çalışır, başka latest kaydını okumaz. Erişilemeyen dizinler de raporun erişilemeyenler bölümüne girer.
- Devamda yeni okuma/yeni dosya yoksa kurtarma planlayıcıyı kilitlemez ve yeniden taradım demez. Bütün katalog denemeleri tamamlanınca aynı turda mevcut kalıcı planlayıcıya döner; hedefler otomatik başarılı yapılmaz. Gerekiyorsa mevcut kota/sağlayıcı sınırları geçerlidir. Kaynak/kurum sözcüklerinin ekli/çoğul biçimleri kullanıcıya devredilen kamuya açık seçim sayılır; izin, gönderim, kişisel bilgi ve açık dar kapsam soruları korunur.
- Normal goal planlayıcısı etkin uzmanların küçük kataloğunu aynı çağrıda görür ve isteğe bağlı specialist kimliği seçer. brain_delegate seçimi mevcut team_center atamasıyla doğrular; specialist_orchestrator.execute_step aynı journal/checkpoint/dependencies/approval üzerinden goal_tools çalıştırır. Yeni bağımsız planlayıcı/model çağrısı veya ikinci görev günlüğü açılmaz. Eski specialist seçimleri korunur; kullanıcı/dosya/hesap izinleri uzman adıyla genişlemez.
- test_durable_recovery_variations: gerçek dosyalı dört dizin, kurtarma-only devam, ilk bozuk/ikinci geçerli haber, final kanıt kapısı, tekrar etmeyen çıktı, soru varyasyonları, sahiplik/iptal ve gerçek not adaptöründe uzman seçimi. Dış ağ/model/Bridge taşıması taklittir; dosya, seal/verify ve günlük gerçek çalışır. Windows canlı araştırma ve sağlayıcı kabulü ayrı kalır.

## Ortak görev çekirdeği — 13 Ekim 2026

- Ana plan `docs/JARVIS_ANA_PLAN.md` içindedir. Mevcut motor korunur; yeni ajan framework'ü kurulmadı. Arayüz/ses/Android değişmez.
- `task_agents` kalıcı adımları sürdürür: `görev devam [kimlik]`, `görev sürdür [kimlik]`, `görev iptal [kimlik]`, `görev durumu [kimlik]`, `görev geçmişi`, `görev yetenekleri`. Tamamlanan adımlar tekrarlanmaz. `görevlerim` eski takvim/hatırlatma yoluna bırakıldı.
- Kesilen araştırma/rapor/doğrulama sürdürülür; tarayıcı/kod adımının dış etkisi belirsizse otomatik tekrar uygulanmaz. Bekleyen onay yalnız aynı görevin kimliğiyle tüketilir/iptal edilir.
- Rapor SHA-256 özeti, adım denemeleri ve son 256 durum geçişi kaydedilir. Eksik/değişmiş dosya devamı engeller. Eski raporlarda hash yoksa yalnız varlık doğrulanabilir.
- Görev kayıtları atomik değiştirme öncesi flush/fsync kullanır; saklama başarısızsa iş başlatılmaz. Sonucu gecikmiş iptal görevi başarıya çeviremez.
- Her görev `llm` kullanıcı bağlamında yürür ve sonunda önceki bağlam geri gelir. Yerel önceki görev araması kullanıcıya özeldir; en çok 3 ilgili tamamlanmış görevi planlayıcıya veri olarak verir, yeni model çağrısı üretmez.
- Kurtarma otomatiktir denmez: `görev devam` ile kullanıcı başlatır; dış işlemler mevcut onay sınırını korur. Yeni sürekli arka plan servisi yoktur.
- `tests/test_task_recovery.py` kesinti, iptal yarışı, değiştirilmiş çıktı, disk hatası, sahiplik, geçmiş ve model bağlamını denetler. Tam Windows doğrulaması kullanıcı PC'sinde yapılmalıdır.

## Araç sonuçlarının doğrulanması — 13 Ekim 2026

- `task_results` tamamlanan gerçek worker çıktısını türüne göre denetler. Kaynak okuma kaydı, rapor SHA-256 özeti, test edilmiş kod taslağı, doğrulanmış tarayıcı adımları ve ekran dosyası gerekir.
- Kodda `draft_test_ok=None` veya False başarı değildir; taslak yoksa kod işi tamamlanmaz. Geliştirme kilidi ve uygulama izinleri korunur.
- Tarayıcı onayından dönen sonuç aynı sözleşmeden geçer. Devam ve bağımlı adımlar mevcut kanıt dosyalarını yeniden kontrol eder. Eksik kanıtla dış işlemi tekrarlama.
- Eski kayıtlar silinmez; sözleşmesiz eski çıktı yeni verify adımında kanıt sayılamaz. İçerik doğruluğu bu yerel kontrollerle garanti edilmez. Yeni servis veya bağımlılık yoktur.

## Ortak araç girdisi ve yürütme kaydı — 13 Ekim 2026

- `task_tools` mevcut beş worker için izinli girdi alanları, metin sınırları, risk ve tekrar yürütme sınıfını tanımlar. Plan doğrulamada sağlanan alanlar kontrol edilir; zorunlu alanlar gerçek worker çağrılmadan önce aranır. Eksik alan bir adımı başarısız yapar, sonraki bağımlı adımlar durur; bağımsız adımlar çalışabilir.
- Her denemede kullanıcı/görev/adım/yetenek/risk/deneme kaydı dış çağrıdan önce diske yazılır. Modelin verdiği `execution` alanı kullanılmaz. Bu kayıt yetki veya onay sağlamaz; mevcut tarayıcı onayı, gizlilik ve geliştirme kilidi geçerlidir.
- `effect_unknown` tarayıcı/kod başarısızlığını ihtiyatlı sınıflandırır; dış işlem kesin gerçekleşti demek değildir. Bu adımlar otomatik tekrar edilmez. Araştırma/rapor/doğrulama yeniden yürütme sınıfı mevcut davranıştır; rapor yeni dosya üretebilir.
- Yeni test: `tests/test_task_tools.py`. Mevcut motor/JSON kayıtları korunur; LangGraph/Hindsight/Paperclip kurulmadı. Android, arayüz ve ses değişmez.

## Capability Manifest uyumluluk görünümü — 23 Ekim 2026

- `modules/capability_manifest.py`, mevcut `tool_contract`, `task_tools` ve `goal_tools` kataloglarını salt-okunur, JSON-uyumlu Capability Manifest görünümüne taşır; callable/binding ayrıntıları dispatcher ve mevcut kaynak modüllerde kalır.
- Bu adaptör yeni execution engine, planner veya araç kataloğu değildir. Yinelenen capability ID ile bilinmeyen sürüm, permission veya effect politikası fail-closed reddedilir; mevcut tool discovery ve yürütme davranışı değişmez.
- Test: `tests/test_capability_manifest.py`; read ve yan-etkili görünüm, JSON sınırı ve discovery uyumluluğu denetlenir.

## Hesap araçları başlangıcı — 13 Ekim 2026

- `account_tools` ortak servis sınırıdır; ilk uygulanan işlem Gmail `list_unread`. Mevcut kullanıcıya özel `google_api._service(..., interactive=False)` yolunu kullanır. Gövde okumaz, mail göndermez, okunmuş işaretlemez ve kendiliğinden OAuth ekranı açmaz.
- `account` worker görev planlayıcısı, risk/kurtarma ve sonuç doğrulamasına bağlıdır. `görev mail oku` modelsiz başlatır; `hesap bağlantıları`/`hesap yetenekleri` destek kataloğunu verir, bağlı hesap durumu değildir.
- Sonuç, kullanıcı/okuma zamanı/sorgu/limit/mesaj kimlikleri/From/Subject/ilk sayfa bilgisi ve SHA-256 kaydını içerir. Bu geçmiş anlık görüntüdür; devam/verify Gmail'i yeniden okumaz, güncel posta durumunu garanti etmez. Başlıklar kullanıcıya özel görev JSON'unda kalır; anahtar/token kaydedilmez.
- Sadece açık görev kullanıcı bağlamı hesap okuyabilir; gizli/yerel modda web kontrolü okumayı engeller. Desteklenmeyen servis/işlem `unavailable` döner ve eski WhatsApp otomasyonuna otomatik düşmez.
- Gmail gönderim, Telegram, resmi WhatsApp, YouTube/Instagram yayın ve sürekli takip açık iştir. Gerçek OAuth/hesap ve Windows denemeleri bekliyor. Yeni framework/bağımlılık/arayüz değişikliği yoktur.
